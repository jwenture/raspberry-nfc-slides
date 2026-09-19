import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
config_dir = project_root / "config"


def generate_image(text: str, output_path: Path, width: int = 800, height: int = 480) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), color="black")
    draw = ImageDraw.Draw(img)

    font = None
    for font_name in ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf"]:
        try:
            font = ImageFont.truetype(font_name, 48)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (width - text_width) // 2
    y = (height - text_height) // 2
    draw.text((x, y), text, fill="white", font=font)
    img.save(str(output_path))
    print(f"Generated: {output_path}")


def main() -> None:
    generate_image("Tap a card", config_dir / "idle.png")
    generate_image("Unknown card", config_dir / "error.png")


if __name__ == "__main__":
    main()
