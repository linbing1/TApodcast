import json
import logging
import os
from datetime import date
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
TITLE_FONT_SIZE = 96
MIN_TITLE_FONT_SIZE = 72
TITLE_FONT_STEP = 2
TITLE_LINE_HEIGHT = 120
TITLE_STROKE_WIDTH = 2
TITLE_PUNCTUATION = frozenset("，。！？：；、,.!?;:")
TITLE_PROTECTED_PHRASES = tuple(
    sorted(
        {
            "刘易斯-斯凯利",
            "阿森纳",
            "心属阿森纳",
            "曼联",
            "切尔西",
            "利物浦",
            "曼城",
            "热刺",
            "纽卡斯尔",
            "西汉姆",
            "水晶宫",
            "诺丁汉森林",
            "阿斯顿维拉",
            "布莱顿",
            "伯恩茅斯",
            "巴黎圣日耳曼",
            "皇家马德里",
            "巴塞罗那",
            "拜仁慕尼黑",
            "国际米兰",
            "英超",
            "欧冠",
            "世界杯",
            "欧洲杯",
            "转会市场",
            "青训学院",
            "一线队",
        },
        key=len,
        reverse=True,
    )
)
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


def _load_date_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        os.getenv("COVER_DATE_FONT_PATH", ""),
        "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return _load_font(size)


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    stroke_width: int = 0,
) -> int:
    bounds = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return bounds[2] - bounds[0]


def _title_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> int:
    return _text_width(draw, text, font, stroke_width=TITLE_STROKE_WIDTH)


def _format_cover_date(value: date | None = None) -> str:
    return (value or date.today()).strftime("%Y.%m.%d")


def _title_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue

        phrase = next(
            (candidate for candidate in TITLE_PROTECTED_PHRASES if text.startswith(candidate, index)),
            "",
        )
        if phrase:
            tokens.append(phrase)
            index += len(phrase)
            continue

        if text[index].isascii() and (text[index].isalnum() or text[index] in "-_+&./"):
            end = index + 1
            while end < len(text) and text[end].isascii() and (
                text[end].isalnum() or text[end] in "-_+&./"
            ):
                end += 1
            tokens.append(text[index:end])
            index = end
            continue

        if text[index] in TITLE_PUNCTUATION:
            if tokens:
                tokens[-1] += text[index]
            else:
                tokens.append(text[index])
        else:
            tokens.append(text[index])
        index += 1
    return tokens


def _break_score(tokens: list[str], boundary: int) -> int:
    previous = tokens[boundary - 1].rstrip()
    following = tokens[boundary].lstrip()
    score = 0
    if previous and previous[-1] in TITLE_PUNCTUATION:
        score += 1000
    if following and following[0] in TITLE_PUNCTUATION:
        score -= 1000
    if previous in TITLE_PROTECTED_PHRASES:
        score += 10
    return score


def _join_tokens(tokens: list[str]) -> str:
    return "".join(tokens).strip()


def _best_two_line_split(
    tokens: list[str],
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
) -> list[str] | None:
    candidates: list[tuple[int, int, int, int]] = []
    for boundary in range(1, len(tokens)):
        first = _join_tokens(tokens[:boundary])
        second = _join_tokens(tokens[boundary:])
        first_width = _title_width(draw, first, font)
        second_width = _title_width(draw, second, font)
        if first_width <= MAX_TITLE_WIDTH and second_width <= MAX_TITLE_WIDTH:
            balance = abs(first_width - second_width)
            candidates.append((_break_score(tokens, boundary), -balance, -max(first_width, second_width), boundary))
    if not candidates:
        return None
    boundary = max(candidates)[3]
    return [_join_tokens(tokens[:boundary]), _join_tokens(tokens[boundary:])]


def _wrap_title_tokens(
    tokens: list[str],
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
) -> list[str]:
    lines: list[str] = []
    remaining = tokens[:]
    while remaining:
        full_line = _join_tokens(remaining)
        if _title_width(draw, full_line, font) <= MAX_TITLE_WIDTH:
            lines.append(full_line)
            break

        candidates: list[tuple[int, int, int]] = []
        for boundary in range(1, len(remaining) + 1):
            line = _join_tokens(remaining[:boundary])
            width = _title_width(draw, line, font)
            if width <= MAX_TITLE_WIDTH:
                candidates.append((_break_score(remaining, boundary) if boundary < len(remaining) else 0, width, boundary))
        if not candidates:
            lines.append(remaining[0])
            remaining = remaining[1:]
            continue

        boundary = max(candidates)[2]
        lines.append(_join_tokens(remaining[:boundary]))
        remaining = remaining[boundary:]
    return lines


def _split_title(
    title: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
) -> list[str]:
    title = title.replace("\\n", "\n").strip()
    if not title:
        return []
    lines: list[str] = []
    for explicit_line in title.splitlines():
        tokens = _title_tokens(explicit_line.strip())
        if not tokens:
            continue
        two_line_split = _best_two_line_split(tokens, draw, font)
        if two_line_split:
            lines.extend(two_line_split)
        else:
            lines.extend(_wrap_title_tokens(tokens, draw, font))
    return lines


def _fit_title(
    title: str,
    draw: ImageDraw.ImageDraw,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(TITLE_FONT_SIZE, MIN_TITLE_FONT_SIZE - 1, -TITLE_FONT_STEP):
        font = _load_font(size)
        lines = _split_title(title, draw, font)
        if len(lines) <= 2:
            return font, lines

    font = _load_font(MIN_TITLE_FONT_SIZE)
    return font, _split_title(title, draw, font)


def _draw_cover_text(
    canvas: Image.Image,
    title: str,
    kicker: str,
    subtitle: str,
    brand: str,
    date_text: str,
) -> None:
    draw = ImageDraw.Draw(canvas)
    title_font, title_lines = _fit_title(title, draw)
    kicker_font = _load_font(34)
    date_font = _load_date_font(60)
    meta_font = _load_font(28)
    kicker_position = (LEFT_MARGIN, 150)
    draw.text(kicker_position, kicker, font=kicker_font, fill=ACCENT)
    kicker_bounds = draw.textbbox(kicker_position, kicker, font=kicker_font)
    date_bounds = draw.textbbox((0, 0), date_text, font=date_font)
    date_width = date_bounds[2] - date_bounds[0]
    date_x = COVER_WIDTH - LEFT_MARGIN - date_width - date_bounds[0]
    date_y = kicker_bounds[1] - date_bounds[1]
    draw.text((date_x, date_y), date_text, font=date_font, fill=ACCENT)
    draw.rounded_rectangle(
        (LEFT_MARGIN, 215, LEFT_MARGIN + 110, 223),
        radius=4,
        fill=ACCENT,
    )

    title_y = 1110 if len(title_lines) > 1 else 1170
    for index, line in enumerate(title_lines):
        draw.text(
            (LEFT_MARGIN, title_y + index * TITLE_LINE_HEIGHT),
            line,
            font=title_font,
            fill=WHITE if index == 0 else ACCENT,
            stroke_width=TITLE_STROKE_WIDTH,
            stroke_fill="#000000",
        )

    if subtitle:
        subtitle_y = title_y + len(title_lines) * TITLE_LINE_HEIGHT + 60
        draw.text((LEFT_MARGIN, subtitle_y), subtitle, font=kicker_font, fill=WHITE)
        rule_y = subtitle_y + 100
    else:
        rule_y = title_y + len(title_lines) * TITLE_LINE_HEIGHT + 50

    draw.line((LEFT_MARGIN, rule_y, COVER_WIDTH - LEFT_MARGIN, rule_y), fill="#3b3d45", width=2)
    draw.text((LEFT_MARGIN, rule_y + 50), brand, font=meta_font, fill=MUTED)


def render_cover(
    image_path: str,
    title: str,
    output_path: str,
    kicker: str = "英超新闻 · 深度报道",
    subtitle: str = "",
    brand: str = "英超每日观察",
    date_text: str = "",
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

    _draw_cover_text(
        canvas,
        title,
        kicker,
        subtitle,
        brand,
        date_text or _format_cover_date(),
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output, "PNG", optimize=True)
    logger.info("Cover saved to %s", output)
    return str(output)


def generate_cover(
    output_dir: str,
    title: str = "",
    image_index: int | None = None,
    kicker: str = "英超新闻 · 深度报道",
    subtitle: str = "",
    brand: str = "英超每日观察",
    date_text: str = "",
    output_name: str = "cover.png",
) -> str:
    image_dir = Path(output_dir) / "images"
    image_paths = sorted(
        path for path in image_dir.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ) if image_dir.exists() else []
    if not image_paths:
        raise FileNotFoundError(f"No images found in {image_dir}")

    if image_index is None:
        metadata_paths = [Path(output_dir) / "page.json", Path(output_dir) / "cover.json"]
        for metadata_path in metadata_paths:
            if not metadata_path.exists():
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("cover_image_index") is not None:
                image_index = int(metadata["cover_image_index"])
                break
            if metadata.get("image_index") is not None:
                image_index = int(metadata["image_index"])
                break
        if image_index is None:
            image_index = 0

    indexed_path = image_dir / f"{image_index:03d}.jpg"
    if indexed_path.exists():
        image_path = indexed_path
    elif image_index < 0 or image_index >= len(image_paths):
        raise IndexError(f"Image index {image_index} is out of range for {image_dir}")
    else:
        image_path = image_paths[image_index]

    if not title:
        for title_name in ("title.txt", "publish_title.txt"):
            title_path = Path(output_dir) / title_name
            if title_path.exists():
                title = title_path.read_text(encoding="utf-8").strip()
                if title:
                    break
    if not title:
        raise ValueError(f"No cover title found in {output_dir}")

    return render_cover(
        image_path=str(image_path),
        title=title,
        output_path=str(Path(output_dir) / output_name),
        kicker=kicker,
        subtitle=subtitle,
        brand=brand,
        date_text=date_text,
    )
