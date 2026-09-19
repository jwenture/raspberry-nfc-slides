import logging
import shutil
import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.config import Config, setup_logging
from src.tag_mapper import TagMapper, TagInfo
from sync.transcode import transcode_video, resize_image

logger = logging.getLogger(__name__)

MIN_FREE_DISK_BYTES = 1024 * 1024 * 1024


def _check_disk_space(path: Path) -> None:
    usage = shutil.disk_usage(path)
    if usage.free < MIN_FREE_DISK_BYTES:
        logger.warning(
            "Low disk space: %.1f GB free on %s",
            usage.free / (1024 * 1024 * 1024),
            path,
        )


def _run_rclone(remote_path: str, raw_dir: Path, config: Config) -> bool:
    cmd = [
        "rclone", "sync",
        remote_path,
        str(raw_dir),
        "--config", str(config.paths.rclone_config),
    ] + config.sync.rclone_flags.split()
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(
            "rclone sync failed for %s: %s",
            remote_path,
            result.stderr.strip(),
        )
        return False
    logger.debug("rclone stdout: %s", result.stdout)
    logger.debug("rclone stderr: %s", result.stderr)
    return True


def _process_tag(tag: TagInfo, config: Config) -> tuple[int, int, int]:
    raw_dir = config.paths.cache_dir / tag.uid / "raw"
    processed_dir = config.paths.cache_dir / tag.uid / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    _check_disk_space(raw_dir)

    if not _run_rclone(tag.remote_path, raw_dir, config):
        return 0, 0, 0

    width = config.screen.width
    height = config.screen.height
    video_exts = set(config.sync.supported_video_extensions)
    image_exts = set(config.sync.supported_image_extensions)

    synced_count = 0
    video_count = 0
    image_count = 0

    for raw_file in sorted(raw_dir.iterdir()):
        if not raw_file.is_file():
            continue
        synced_count += 1
        ext = raw_file.suffix.lower()
        if ext in video_exts:
            output = processed_dir / f"{raw_file.stem}.mp4"
            if transcode_video(str(raw_file), str(output), width, height):
                video_count += 1
        elif ext in image_exts:
            output = processed_dir / f"{raw_file.stem}.jpg"
            if resize_image(str(raw_file), str(output), width, height):
                image_count += 1

    if not config.sync.keep_raw:
        shutil.rmtree(raw_dir)
        logger.info("Removed raw directory for tag %s", tag.uid)

    return synced_count, video_count, image_count


def main() -> None:
    settings_path = project_root / "config" / "settings.yaml"
    config = Config.load(settings_path)
    setup_logging(config.sync.log_file)

    logger.info("Starting sync")

    try:
        tag_mapper = TagMapper(project_root / "config" / "tags.json")
        tags = tag_mapper.all_tags()

        total_synced = 0
        total_videos = 0
        total_images = 0

        for tag in tags:
            try:
                synced, videos, images = _process_tag(tag, config)
                total_synced += synced
                total_videos += videos
                total_images += images
                logger.info(
                    "Tag %s (%s): synced %d files, transcoded %d videos, resized %d images",
                    tag.uid,
                    tag.name,
                    synced,
                    videos,
                    images,
                )
            except Exception:
                logger.exception(
                    "Failed to process tag %s (%s)",
                    tag.uid,
                    tag.name,
                )

        logger.info(
            "Sync complete: %d tags, %d files synced, %d videos transcoded, %d images resized",
            len(tags),
            total_synced,
            total_videos,
            total_images,
        )
    except Exception:
        logger.exception("Sync failed")


if __name__ == "__main__":
    main()
