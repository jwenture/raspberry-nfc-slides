import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _should_skip(input_path: Path, output_path: Path) -> bool:
    if not output_path.exists():
        return False
    return output_path.stat().st_mtime >= input_path.stat().st_mtime


def _build_vf(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )


def _run_ffmpeg(args: list[str]) -> bool:
    try:
        result = subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError:
        logger.error("ffmpeg not found")
        return False
    except Exception as exc:
        logger.error("ffmpeg error: %s", exc)
        return False
    if result.returncode != 0:
        logger.error(
            "ffmpeg failed (rc=%d): %s", result.returncode, result.stderr.strip()
        )
        return False
    return True


def _run_transcode(
    src: Path,
    dst: Path,
    width: int,
    height: int,
    extra_args: list[str],
) -> bool:
    vf = _build_vf(width, height)
    args = ["ffmpeg", "-i", str(src), "-vf", vf, *extra_args, "-y", str(dst)]
    return _run_ffmpeg(args)


def transcode_video(
    input_path: str, output_path: str, width: int, height: int
) -> bool:
    src = Path(input_path)
    dst = Path(output_path)

    if not src.exists():
        logger.error("Input video not found: %s", src)
        return False

    if _should_skip(src, dst):
        logger.info("Skipping video transcode (up to date): %s", dst)
        return True

    dst.parent.mkdir(parents=True, exist_ok=True)

    extra_args = [
        "-c:v", "h264",
        "-profile:v", "baseline",
        "-level", "3.1",
        "-preset", "fast",
        "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-an",
        "-movflags", "+faststart",
    ]

    if _run_transcode(src, dst, width, height, extra_args):
        logger.info("Transcoded video: %s -> %s", src, dst)
        return True

    return False


def resize_image(
    input_path: str, output_path: str, width: int, height: int
) -> bool:
    src = Path(input_path)
    dst = Path(output_path)

    if not src.exists():
        logger.error("Input image not found: %s", src)
        return False

    if _should_skip(src, dst):
        logger.info("Skipping image resize (up to date): %s", dst)
        return True

    dst.parent.mkdir(parents=True, exist_ok=True)

    if _run_transcode(src, dst, width, height, []):
        logger.info("Resized image: %s -> %s", src, dst)
        return True

    if src.suffix.lower() == ".heic":
        logger.warning(
            "ffmpeg failed on HEIC, trying heif-convert fallback: %s", src
        )
        temp_png = dst.with_suffix(".tmp.png")
        try:
            try:
                result = subprocess.run(
                    ["heif-convert", str(src), str(temp_png)],
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                logger.error("heif-convert not found")
                return False
            except Exception as exc:
                logger.error("heif-convert error: %s", exc)
                return False
            if result.returncode != 0:
                logger.error(
                    "heif-convert failed (rc=%d): %s",
                    result.returncode,
                    result.stderr.strip(),
                )
                return False
            if _run_transcode(temp_png, dst, width, height, []):
                logger.info(
                    "Resized image via heif-convert: %s -> %s", src, dst
                )
                return True
            return False
        finally:
            if temp_png.exists():
                temp_png.unlink()

    return False
