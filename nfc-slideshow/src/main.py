import enum
import logging
import signal
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.config import Config, setup_logging
from src.nfc_reader import NfcReader
from src.slideshow import Slideshow
from src.tag_mapper import TagMapper, UnknownTagError

logger = logging.getLogger(__name__)

_shutdown = False


class State(enum.Enum):
    IDLE = "idle"
    PLAYING = "playing"
    ERROR = "error"


def _signal_handler(sig, frame):
    global _shutdown
    _shutdown = True


def _discover_media(processed_dir: Path) -> list[str]:
    if not processed_dir.exists():
        return []
    return sorted(str(f) for f in processed_dir.iterdir() if f.is_file())


def main() -> None:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    settings_path = project_root / "config" / "settings.yaml"
    config = Config.load(settings_path)
    setup_logging(config.paths.log_file)

    logger.info("Starting NFC Slideshow")

    slideshow = Slideshow(config)
    slideshow.play_idle(str(config.paths.idle_image))

    try:
        nfc_reader = NfcReader(
            i2c_bus=config.nfc.i2c_bus,
            i2c_address=config.nfc.i2c_address,
            poll_interval=config.nfc.poll_interval,
            debounce_seconds=config.nfc.debounce_seconds,
        )
    except Exception as e:
        logger.error("NFC reader initialization failed: %s", e)
        logger.error("Showing error screen — fix the issue and restart the service")
        slideshow.play_idle(str(config.paths.error_image))
        while not _shutdown:
            time.sleep(1)
        slideshow.cleanup()
        return

    tag_mapper = TagMapper(project_root / "config" / "tags.json")

    state = State.IDLE
    current_uid: str | None = None
    tag_removal_time: float | None = None
    last_tags_check = time.monotonic()

    logger.info("Entering main loop (state=%s)", state.value)

    try:
        while not _shutdown:
            now = time.monotonic()
            if now - last_tags_check > config.slideshow.tags_reload_interval:
                tag_mapper.maybe_reload()
                last_tags_check = now

            uid = nfc_reader.poll()

            if uid is not None:
                tag_removal_time = None
                try:
                    tag = tag_mapper.lookup(uid)
                    media_dir = config.paths.cache_dir / tag.uid / "processed"
                    media_files = _discover_media(media_dir)
                    if media_files:
                        slideshow.play_playlist(media_files)
                        state = State.PLAYING
                        current_uid = uid
                        logger.info(
                            "Playing tag %s (%s): %d files",
                            uid,
                            tag.name,
                            len(media_files),
                        )
                    else:
                        slideshow.play_image(str(config.paths.error_image), 5.0)
                        state = State.ERROR
                        logger.warning(
                            "Tag %s (%s): no media files in %s",
                            uid,
                            tag.name,
                            media_dir,
                        )
                except UnknownTagError:
                    slideshow.play_image(str(config.paths.error_image), 3.0)
                    state = State.ERROR
                    logger.warning("Unknown tag UID: %s", uid)

            elif state == State.PLAYING:
                if not nfc_reader.is_tag_present():
                    if tag_removal_time is None:
                        tag_removal_time = time.monotonic()
                        logger.info("Tag removed, starting idle timeout")
                    elif (
                        time.monotonic() - tag_removal_time
                        > config.slideshow.idle_timeout
                    ):
                        slideshow.play_idle(str(config.paths.idle_image))
                        state = State.IDLE
                        current_uid = None
                        tag_removal_time = None
                        logger.info("Idle timeout reached, returning to idle")
                else:
                    tag_removal_time = None

            elif state == State.ERROR:
                if slideshow.update():
                    slideshow.play_idle(str(config.paths.idle_image))
                    state = State.IDLE
                    logger.info("Error display finished, returning to idle")

            if nfc_reader.is_tag_present():
                time.sleep(config.nfc.poll_interval)

    except Exception as e:
        logger.exception("Unexpected error in main loop: %s", e)
    finally:
        logger.info("Shutdown signal received")
        nfc_reader.cleanup()
        slideshow.cleanup()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
