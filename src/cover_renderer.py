import json
import logging
import os
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.subtitle_renderer import find_cjk_font

logger = logging.getLogger(__name__)

# 竖版封面 1080x1920：顶部留白，中部主图，下方标题和品牌。
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

# 横版封面 1920x1080：主图全幅铺底，顶部栏目/日期，底部标题和品牌。
LAND_WIDTH = 1920
LAND_HEIGHT = 1080
LAND_MARGIN = 76
LAND_MAX_TITLE_WIDTH = LAND_WIDTH - LAND_MARGIN * 2
LAND_TITLE_FONT_SIZE = 88
LAND_MIN_TITLE_FONT_SIZE = 64
LAND_TITLE_LINE_HEIGHT = 108
LAND_TOP_MARGIN = 84
LAND_BOTTOM_MARGIN = 84

# 两种版式共用。
TITLE_STROKE_WIDTH = 2
META_BOTTOM_GAP = 48
META_BAR_GAP = 30
META_BAR_WIDTH = 110
META_BAR_HEIGHT = 8
KICKER_FONT_SIZE = 34
DATE_FONT_SIZE = 60
BRAND_FONT_SIZE = 28
BRAND_GAP_ABOVE = 50

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
    max_width: int = MAX_TITLE_WIDTH,
) -> list[str] | None:
    candidates: list[tuple[int, int, int, int]] = []
    for boundary in range(1, len(tokens)):
        first = _join_tokens(tokens[:boundary])
        second = _join_tokens(tokens[boundary:])
        first_width = _title_width(draw, first, font)
        second_width = _title_width(draw, second, font)
        if first_width <= max_width and second_width <= max_width:
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
    max_width: int = MAX_TITLE_WIDTH,
) -> list[str]:
    lines: list[str] = []
    remaining = tokens[:]
    while remaining:
        full_line = _join_tokens(remaining)
        if _title_width(draw, full_line, font) <= max_width:
            lines.append(full_line)
            break

        candidates: list[tuple[int, int, int]] = []
        for boundary in range(1, len(remaining) + 1):
            line = _join_tokens(remaining[:boundary])
            width = _title_width(draw, line, font)
            if width <= max_width:
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
    max_width: int = MAX_TITLE_WIDTH,
) -> list[str]:
    title = title.replace("\\n", "\n").strip()
    if not title:
        return []
    lines: list[str] = []
    for explicit_line in title.splitlines():
        tokens = _title_tokens(explicit_line.strip())
        if not tokens:
            continue
        two_line_split = _best_two_line_split(tokens, draw, font, max_width)
        if two_line_split:
            lines.extend(two_line_split)
        else:
            lines.extend(_wrap_title_tokens(tokens, draw, font, max_width))
    return lines


def _fit_title(
    title: str,
    draw: ImageDraw.ImageDraw,
    max_width: int = MAX_TITLE_WIDTH,
    max_size: int = TITLE_FONT_SIZE,
    min_size: int = MIN_TITLE_FONT_SIZE,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(max_size, min_size - 1, -TITLE_FONT_STEP):
        font = _load_font(size)
        lines = _split_title(title, draw, font, max_width)
        if len(lines) <= 2:
            return font, lines

    font = _load_font(min_size)
    return font, _split_title(title, draw, font, max_width)


def _draw_meta_row(
    draw: ImageDraw.ImageDraw,
    canvas_width: int,
    margin: int,
    kicker: str,
    kicker_top: int,
    kicker_font: ImageFont.FreeTypeFont,
    date_text: str,
    date_font: ImageFont.FreeTypeFont,
) -> None:
    """栏目标签居左、日期居右顶部对齐，装饰条在标签上方 META_BAR_GAP 处。"""
    kicker_bounds = draw.textbbox((0, 0), kicker, font=kicker_font)
    date_bounds = draw.textbbox((0, 0), date_text, font=date_font)
    kicker_ink_top = kicker_top + kicker_bounds[1]
    draw.text((margin, kicker_top), kicker, font=kicker_font, fill=ACCENT)
    date_width = date_bounds[2] - date_bounds[0]
    date_x = canvas_width - margin - date_width - date_bounds[0]
    draw.text((date_x, kicker_ink_top - date_bounds[1]), date_text, font=date_font, fill=ACCENT)
    bar_bottom = kicker_ink_top - META_BAR_GAP
    draw.rounded_rectangle(
        (margin, bar_bottom - META_BAR_HEIGHT, margin + META_BAR_WIDTH, bar_bottom),
        radius=4,
        fill=ACCENT,
    )


def _draw_title_lines(
    draw: ImageDraw.ImageDraw,
    margin: int,
    title_lines: list[str],
    title_font: ImageFont.FreeTypeFont,
    title_y: int,
    line_height: int,
) -> None:
    """标题首行白色、其余行黄色，带黑色描边。"""
    for index, line in enumerate(title_lines):
        draw.text(
            (margin, title_y + index * line_height),
            line,
            font=title_font,
            fill=WHITE if index == 0 else ACCENT,
            stroke_width=TITLE_STROKE_WIDTH,
            stroke_fill="#000000",
        )


def _draw_brand_footer(
    draw: ImageDraw.ImageDraw,
    canvas_width: int,
    margin: int,
    rule_y: int,
    rule_fill,
    brand: str,
    brand_font: ImageFont.FreeTypeFont,
) -> None:
    """标题区下方的分隔线和品牌文字。"""
    draw.line((margin, rule_y, canvas_width - margin, rule_y), fill=rule_fill, width=2)
    draw.text((margin, rule_y + BRAND_GAP_ABOVE), brand, font=brand_font, fill=MUTED)


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
    kicker_font = _load_font(KICKER_FONT_SIZE)
    date_font = _load_date_font(DATE_FONT_SIZE)
    meta_font = _load_font(BRAND_FONT_SIZE)

    # 栏目行锚定主图顶部：最高的日期文字底部距主图 META_BOTTOM_GAP。
    kicker_bounds = draw.textbbox((0, 0), kicker, font=kicker_font)
    date_bounds = draw.textbbox((0, 0), date_text, font=date_font)
    date_height = date_bounds[3] - date_bounds[1]
    kicker_top = PHOTO_TOP - META_BOTTOM_GAP - kicker_bounds[1] - date_height
    _draw_meta_row(draw, COVER_WIDTH, LEFT_MARGIN, kicker, kicker_top, kicker_font, date_text, date_font)

    title_y = 1110 if len(title_lines) > 1 else 1170
    _draw_title_lines(draw, LEFT_MARGIN, title_lines, title_font, title_y, TITLE_LINE_HEIGHT)

    if subtitle:
        subtitle_y = title_y + len(title_lines) * TITLE_LINE_HEIGHT + 60
        draw.text((LEFT_MARGIN, subtitle_y), subtitle, font=kicker_font, fill=WHITE)
        rule_y = subtitle_y + 100
    else:
        rule_y = title_y + len(title_lines) * TITLE_LINE_HEIGHT + 50

    _draw_brand_footer(draw, COVER_WIDTH, LEFT_MARGIN, rule_y, "#3b3d45", brand, meta_font)


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


def _draw_landscape_text(
    canvas: Image.Image,
    title: str,
    kicker: str,
    subtitle: str,
    brand: str,
    date_text: str,
) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    title_font, title_lines = _fit_title(
        title,
        draw,
        max_width=LAND_MAX_TITLE_WIDTH,
        max_size=LAND_TITLE_FONT_SIZE,
        min_size=LAND_MIN_TITLE_FONT_SIZE,
    )
    kicker_font = _load_font(KICKER_FONT_SIZE)
    date_font = _load_date_font(DATE_FONT_SIZE)
    meta_font = _load_font(BRAND_FONT_SIZE)

    _draw_meta_row(draw, LAND_WIDTH, LAND_MARGIN, kicker, LAND_TOP_MARGIN, kicker_font, date_text, date_font)

    # 标题区自底向上排布：品牌文字距底 LAND_BOTTOM_MARGIN。
    rule_y = LAND_HEIGHT - LAND_BOTTOM_MARGIN - 44
    if subtitle:
        title_y = rule_y - len(title_lines) * LAND_TITLE_LINE_HEIGHT - 160
    else:
        title_y = rule_y - len(title_lines) * LAND_TITLE_LINE_HEIGHT - 50
    _draw_title_lines(draw, LAND_MARGIN, title_lines, title_font, title_y, LAND_TITLE_LINE_HEIGHT)

    if subtitle:
        subtitle_y = title_y + len(title_lines) * LAND_TITLE_LINE_HEIGHT + 60
        draw.text((LAND_MARGIN, subtitle_y), subtitle, font=kicker_font, fill=WHITE)

    _draw_brand_footer(draw, LAND_WIDTH, LAND_MARGIN, rule_y, (247, 247, 242, 90), brand, meta_font)


def render_cover_landscape(
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
        (LAND_WIDTH, LAND_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.4),
    )
    canvas = photo.convert("RGBA")

    overlay = Image.new("RGBA", (LAND_WIDTH, LAND_HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    top_fade = LAND_HEIGHT * 0.2
    bottom_start = LAND_HEIGHT * 0.3
    bottom_span = LAND_HEIGHT - bottom_start
    for y in range(LAND_HEIGHT):
        strength = 0
        if y < top_fade:
            strength = max(strength, int(165 * (top_fade - y) / top_fade))
        if y > bottom_start:
            strength = max(strength, int(235 * (y - bottom_start) / bottom_span))
        if strength:
            overlay_draw.line((0, y, LAND_WIDTH, y), fill=(0, 0, 0, strength))
    canvas.alpha_composite(overlay)

    _draw_landscape_text(
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
    logger.info("Landscape cover saved to %s", output)
    return str(output)


def _resolve_cover_inputs(
    output_dir: str,
    title: str,
    image_index: int | None,
) -> tuple[Path, str]:
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

    return image_path, title


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
    image_path, title = _resolve_cover_inputs(output_dir, title, image_index)

    return render_cover(
        image_path=str(image_path),
        title=title,
        output_path=str(Path(output_dir) / output_name),
        kicker=kicker,
        subtitle=subtitle,
        brand=brand,
        date_text=date_text,
    )


def generate_cover_landscape(
    output_dir: str,
    title: str = "",
    image_index: int | None = None,
    kicker: str = "英超新闻 · 深度报道",
    subtitle: str = "",
    brand: str = "英超每日观察",
    date_text: str = "",
    output_name: str = "cover-landscape.png",
) -> str:
    image_path, title = _resolve_cover_inputs(output_dir, title, image_index)

    return render_cover_landscape(
        image_path=str(image_path),
        title=title,
        output_path=str(Path(output_dir) / output_name),
        kicker=kicker,
        subtitle=subtitle,
        brand=brand,
        date_text=date_text,
    )
