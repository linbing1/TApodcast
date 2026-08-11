import logging
import os
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

_W, _H = 1080, 1920
_FPS = 5  # subtitle granularity; ffmpeg will upsample to 30fps

_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def _find_cjk_font() -> str | None:
    for p in _CJK_FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _ts_to_sec(ts: str) -> float:
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return int(parts[0]) * 60 + float(parts[1])


def _parse_subtitles(path: str) -> list[tuple[float, float, str]]:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,.]\d{3}|\d{1,2}:\d{2}[,.]\d{3})"
        r"\s*-->\s*"
        r"(\d{1,2}:\d{2}:\d{2}[,.]\d{3}|\d{1,2}:\d{2}[,.]\d{3})"
        r"[^\n]*\n(.*?)(?=\n\s*\n|\Z)",
        re.DOTALL,
    )
    entries = []
    for m in pattern.finditer(content):
        text = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        if text:
            entries.append((_ts_to_sec(m.group(1)), _ts_to_sec(m.group(2)), text))
    return entries


def _get_subtitle_at(entries: list, t: float) -> str:
    for start, end, text in entries:
        if start <= t < end:
            return text
    return ""


def _composite(img: Image.Image) -> Image.Image:
    """Blurred background (fill) + letterboxed foreground overlay."""
    img_rgb = img.convert("RGB")

    bg_ratio = max(_W / img_rgb.width, _H / img_rgb.height)
    bg_w, bg_h = int(img_rgb.width * bg_ratio), int(img_rgb.height * bg_ratio)
    bg = img_rgb.resize((bg_w, bg_h), Image.LANCZOS)
    bg = bg.crop(((bg_w - _W) // 2, (bg_h - _H) // 2,
                   (bg_w - _W) // 2 + _W, (bg_h - _H) // 2 + _H))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=20))

    fg_ratio = min(_W / img_rgb.width, _H / img_rgb.height)
    fg_w, fg_h = int(img_rgb.width * fg_ratio), int(img_rgb.height * fg_ratio)
    fg = img_rgb.resize((fg_w, fg_h), Image.LANCZOS)

    canvas = bg.copy()
    canvas.paste(fg, ((_W - fg_w) // 2, (_H - fg_h) // 2))
    return canvas


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int,
                   font: ImageFont.FreeTypeFont) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (_W - (bbox[2] - bbox[0])) // 2
    for dx, dy in [(-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, -2), (-2, 2), (2, 2)]:
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=(255, 255, 255))


def _wrap_lines(text: str, font: ImageFont.FreeTypeFont,
                draw: ImageDraw.ImageDraw, max_w: int) -> list[str]:
    lines, line = [], ""
    for ch in text:
        test = line + ch
        if draw.textlength(test, font=font) > max_w and line:
            lines.append(line)
            line = ch
        else:
            line = test
    if line:
        lines.append(line)
    return lines


def render_frames(
    image_paths: list[str],
    duration: float,
    per_image: float,
    srt_path: str,
    title: str,
    article_date: str,
    output_dir: str,
    img_top: int = 600,
    lead_in: float = 0.0,
) -> tuple[str, int]:
    """Render video frames with blurred background and burned-in subtitles.

    Returns (frames_dir, fps).
    """
    font_path = _find_cjk_font()

    def load_font(size: int) -> ImageFont.FreeTypeFont:
        if font_path:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    title_font = load_font(56)
    date_font = load_font(48)
    sub_font = load_font(48)

    subtitles = _parse_subtitles(srt_path)
    n = len(image_paths)

    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for f in os.listdir(frames_dir):
        os.remove(os.path.join(frames_dir, f))

    img_cache: dict[str, Image.Image] = {}

    def get_base(path: str) -> Image.Image:
        if path not in img_cache:
            img_cache[path] = _composite(Image.open(path))
        return img_cache[path].copy()

    frame_interval = 1.0 / _FPS
    total = max(1, int(duration * _FPS) + 1)

    img_bottom = _H - img_top  # y where the letterboxed image ends

    for i in range(total):
        t = i * frame_interval
        frame = get_base(image_paths[int(t / per_image) % n])
        draw = ImageDraw.Draw(frame)

        # Title + date above the image
        if title and img_top > 100:
            title_y = img_top - 80 - 72 - 24
            _draw_centered(draw, title[:20], max(10, title_y), title_font)
            if article_date:
                _draw_centered(draw, article_date, img_top - 80, date_font)

        # Subtitle below the image (offset by lead_in so timing aligns with audio)
        sub_t = t - lead_in
        sub = _get_subtitle_at(subtitles, sub_t) if sub_t >= 0 else ""
        if sub:
            lines = _wrap_lines(sub, sub_font, draw, _W - 80)
            y = img_bottom + 80
            for line in lines:
                _draw_centered(draw, line, y, sub_font)
                y += 64

        frame.save(os.path.join(frames_dir, f"{i:05d}.jpg"), "JPEG", quality=88)
        if i % 100 == 0:
            logger.info("Rendered frame %d/%d (t=%.1fs)", i + 1, total, t)

    logger.info("Rendered %d frames at %dfps", total, _FPS)
    return frames_dir, _FPS
