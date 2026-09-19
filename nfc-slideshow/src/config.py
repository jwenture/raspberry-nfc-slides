import logging
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml


@dataclass
class NfcConfig:
    i2c_bus: int
    i2c_address: int
    poll_interval: float
    debounce_seconds: float


@dataclass
class SlideshowConfig:
    image_duration: float
    loop: bool
    fullscreen: bool
    idle_timeout: int
    tags_reload_interval: int


@dataclass
class PathConfig:
    cache_dir: Path
    rclone_config: Path
    idle_image: Path
    error_image: Path
    log_file: Path


@dataclass
class ScreenConfig:
    width: int
    height: int


@dataclass
class SyncConfig:
    log_file: Path
    keep_raw: bool
    rclone_flags: str
    supported_image_extensions: list[str]
    supported_video_extensions: list[str]


@dataclass
class VlcConfig:
    extra_flags: list[str]


@dataclass
class Config:
    nfc: NfcConfig
    slideshow: SlideshowConfig
    paths: PathConfig
    screen: ScreenConfig
    sync: SyncConfig
    vlc: VlcConfig
    project_root: Path

    @classmethod
    def load(cls, settings_path: str | Path) -> "Config":
        settings_path = Path(settings_path).resolve()
        project_root = settings_path.parent.parent

        with open(settings_path) as f:
            data = yaml.safe_load(f)

        def resolve_path(p: str) -> Path:
            return (project_root / p).resolve()

        return cls(
            nfc=NfcConfig(
                i2c_bus=data["nfc"]["i2c_bus"],
                i2c_address=data["nfc"]["i2c_address"],
                poll_interval=data["nfc"]["poll_interval"],
                debounce_seconds=data["nfc"]["debounce_seconds"],
            ),
            slideshow=SlideshowConfig(
                image_duration=data["slideshow"]["image_duration"],
                loop=data["slideshow"]["loop"],
                fullscreen=data["slideshow"]["fullscreen"],
                idle_timeout=data["slideshow"]["idle_timeout"],
                tags_reload_interval=data["slideshow"]["tags_reload_interval"],
            ),
            paths=PathConfig(
                cache_dir=resolve_path(data["paths"]["cache_dir"]),
                rclone_config=resolve_path(data["paths"]["rclone_config"]),
                idle_image=resolve_path(data["paths"]["idle_image"]),
                error_image=resolve_path(data["paths"]["error_image"]),
                log_file=resolve_path(data["paths"]["log_file"]),
            ),
            screen=ScreenConfig(
                width=data["screen"]["width"],
                height=data["screen"]["height"],
            ),
            sync=SyncConfig(
                log_file=resolve_path(data["sync"]["log_file"]),
                keep_raw=data["sync"]["keep_raw"],
                rclone_flags=data["sync"]["rclone_flags"],
                supported_image_extensions=data["sync"]["supported_image_extensions"],
                supported_video_extensions=data["sync"]["supported_video_extensions"],
            ),
            vlc=VlcConfig(
                extra_flags=data["vlc"]["extra_flags"],
            ),
            project_root=project_root,
        )


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
