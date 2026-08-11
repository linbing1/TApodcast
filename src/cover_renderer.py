import logging
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.subtitle_renderer import find_cjk_font

logger = logging.getLogger(__name__)

COVER_WIDTH = 1080
COVER_HEIGHT = 1920
PHOTO_TOP = 500
PHOTO_HEIGHT = 540
LEFT_MARGIN = 76
MAX_TITLE_WIDTH = COVER_WIDTH - LEFT_MARGIN * 2
ACCENT = "#ffd400"
WHITE = "#f7f7f2"
MUTED = "#b9bbc2"


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    font_path = find_cjk_font()
    if not font_path:
        raise RuntimeError(
            "未找到可用于中文封面的字体。"
            "请安装 Noto Sans CJK SC，或通过 `CJK_FONT_PATH` 指定字体文件。"
        )
    return ImageFont.truetype(font_path, size)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bounds = draw.textbbox((0, 0), text, font=font)
    return bounds[2] - bounds[0]


def _split_title(
    title: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
) -> list[str]:
    title = title.replace("\\n", "\n").strip()
    if not title:
        return []
    explicit_lines = [line.strip() for line in title.splitlines() if line.strip()]
    if len(explicit_lines) > 1:
        return explicit_lines[:2]
    title = explicit_lines[0]
    if _text_width(draw, title, font) <= MAX_TITLE_WIDTH:
        return [title]

    candidates: list[tuple[int, int, int]] = []
    for split_index in range(1, len(title)):
        first_width = _text_width(draw, title[:split_index], font)
        second_width = _text_width(draw, title[split_index:], font)
        if first_width <= MAX_TITLE_WIDTH and second_width <= MAX_TITLE_WIDTH:
            candidates.append(
                (max(first_width, second_width), abs(first_width - second_width), split_index)
            )
    if not candidates:
        return [title[:18], title[18:]]
    split_index = min(candidates)[2]
    return [title[:split_index], title[split_index:]]


def _draw_cover_text(
    canvas: Image.Image,
    title: str,
    kicker: str,
    subtitle: str,
    brand: str,
) -> None:
    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(96)
    kicker_font = _load_font(34)
    meta_font = _load_font(28)
    title_lines = _split_title(title, draw, title_font)

    draw.text((LEFT_MARGIN, 150), kicker, font=kicker_font, fill=ACCENT)
    draw.rounded_rectangle(
        (LEFT_MARGIN, 215, LEFT_MARGIN + 110, 223),
        radius=4,
        fill=ACCENT,
    )

    title_y = 1110 if len(title_lines) > 1 else 1170
    for index, line in enumerate(title_lines):
        draw.text(
            (LEFT_MARGIN, title_y + index * 120),
            line,
            font=title_font,
            fill=WHITE if index == 0 else ACCENT,
            stroke_width=2,
            stroke_fill="#000000",
        )

    if subtitle:
        subtitle_y = title_y + len(title_lines) * 120 + 60
        draw.text((LEFT_MARGIN, subtitle_y), subtitle, font=kicker_font, fill=WHITE)
        rule_y = subtitle_y + 100
    else:
        rule_y = title_y + len(title_lines) * 120 + 50

    draw.line((LEFT_MARGIN, rule_y, COVER_WIDTH - LEFT_MARGIN, rule_y), fill="#3b3d45", width=2)
    draw.text((LEFT_MARGIN, rule_y + 50), brand, font=meta_font, fill=MUTED)


def render_cover(
    image_path: str,
    title: str,
    output_path: str,
    kicker: str = "英超新闻 · 深度报道",
    subtitle: str = "",
    brand: str = "英超每日观察",
) -> str:
    source = Image.open(image_path).convert("RGB")
    photo = ImageOps.fit(
        source,
        (COVER_WIDTH, PHOTO_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    canvas = Image.new("RGBA", (COVER_WIDTH, COVER_HEIGHT), "#08090d")
    canvas.paste(photo, (0, PHOTO_TOP))

    overlay = Image.new("RGBA", (COVER_WIDTH, PHOTO_HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for y in range(PHOTO_HEIGHT):
        strength = int(185 * max(0, (y - PHOTO_HEIGHT * 0.42) / (PHOTO_HEIGHT * 0.58)))
        overlay_draw.line((0, y, COVER_WIDTH, y), fill=(0, 0, 0, strength))
    canvas.alpha_composite(overlay, (0, PHOTO_TOP))

    _draw_cover_text(canvas, title, kicker, subtitle, brand)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output, "PNG", optimize=True)
    logger.info("Cover saved to %s", output)
    return str(output)


def generate_cover(
    output_dir: str,
    title: str = "",
    image_index: int = 0,
    kicker: str = "英超新闻 · 深度报道",
    subtitle: str = "",
    brand: str = "英超每日观察",
    output_name: str = "cover.png",
) -> str:
    image_dir = Path(output_dir) / "images"
    image_paths = sorted(
        path for path in image_dir.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ) if image_dir.exists() else []
    if not image_paths:
        raise FileNotFoundError(f"No images found in {image_dir}")
    if image_index < 0 or image_index >= len(image_paths):
        raise IndexError(f"Image index {image_index} is out of range for {image_dir}")

    if not title:
        title_path = Path(output_dir) / "title.txt"
        if title_path.exists():
            title = title_path.read_text(encoding="utf-8").strip()
    if not title:
        raise ValueError(f"No cover title found in {output_dir}")

    return render_cover(
        image_path=str(image_paths[image_index]),
        title=title,
        output_path=str(Path(output_dir) / output_name),
        kicker=kicker,
        subtitle=subtitle,
        brand=brand,
    )
