import logging
import time

import vlc

logger = logging.getLogger(__name__)

IDLE_IMAGE_DURATION = 86400
IMAGE_PLAY_GRACE_PERIOD = 0.5


class Slideshow:
    def __init__(self, config) -> None:
        self.config = config
        self._image_mode = False
        self._image_start_time: float | None = None
        self._init_vlc()

    def _init_vlc(self) -> None:
        flags = [
            "--no-audio",
            "--fullscreen",
            "--no-osd",
            "--quiet",
            f"--image-duration={int(self.config.slideshow.image_duration)}",
            "--no-video-title-show",
            "--avcodec-hw=mmal",
            "--no-stats",
            "--no-sub-autodetect-file",
        ]
        flags.extend(self.config.vlc.extra_flags)

        self.instance = vlc.Instance(flags)
        self.player = self.instance.media_player_new()
        self.list_player = self.instance.media_list_player_new()
        self.list_player.set_media_player(self.player)

        logger.info("VLC initialized with flags: %s", flags)

    def play_idle(self, image_path: str) -> None:
        logger.info("Playing idle screen: %s", image_path)
        self._image_mode = False
        self._image_start_time = None

        media = self.instance.media_new(image_path)
        media.add_option(f":image-duration={IDLE_IMAGE_DURATION}")
        media_list = self.instance.media_list_new([media])
        self.list_player.set_media_list(media_list)
        self.list_player.set_playback_mode(vlc.PlaybackMode.loop)
        self.list_player.play()

    def play_playlist(self, media_files: list[str], loop: bool = True) -> None:
        logger.info("Playing playlist: %d files", len(media_files))
        self._image_mode = False
        self._image_start_time = None

        media_list = self.instance.media_list_new(media_files)
        self.list_player.set_media_list(media_list)
        if loop:
            self.list_player.set_playback_mode(vlc.PlaybackMode.loop)
        else:
            self.list_player.set_playback_mode(vlc.PlaybackMode.default)
        self.list_player.play()

    def play_image(self, image_path: str, duration: float = 3.0) -> None:
        logger.info("Playing image: %s for %.1fs", image_path, duration)
        self._image_mode = True
        self._image_start_time = time.monotonic()

        media = self.instance.media_new(image_path)
        media.add_option(f":image-duration={int(duration)}")
        media_list = self.instance.media_list_new([media])
        self.list_player.set_media_list(media_list)
        self.list_player.set_playback_mode(vlc.PlaybackMode.default)
        self.list_player.play()

    def update(self) -> bool:
        if self._image_mode and self._image_start_time is not None:
            elapsed = time.monotonic() - self._image_start_time
            if elapsed > IMAGE_PLAY_GRACE_PERIOD and not self.is_playing():
                self._image_mode = False
                self._image_start_time = None
                return True
        return False

    def stop(self) -> None:
        self.list_player.stop()

    def is_playing(self) -> bool:
        return bool(self.player.is_playing())

    def cleanup(self) -> None:
        self.stop()
        logger.info("VLC cleanup complete")
