import logging
import os

from PIL import Image, ImageDraw, ImageFont

from src.subtitle_renderer import find_cjk_font

logger = logging.getLogger(__name__)

_W, _H = 1080, 1920
_FPS = 5  # subtitle granularity; ffmpeg will upsample to 30fps
_CAPTION_MAX_FONT_SIZE = 38
_CAPTION_MIN_FONT_SIZE = 26
_CAPTION_HORIZONTAL_PADDING = 16
_CAPTION_VERTICAL_PADDING = 10
_CAPTION_IMAGE_MARGIN = 18
_CAPTION_GAP = 16
_SUBTITLE_SAFE_TOP = 1380


def _load_caption_font(size: int, font_path: str | None = None) -> ImageFont.FreeTypeFont:
    resolved_path = font_path or find_cjk_font()
    if not resolved_path:
        raise RuntimeError(
            "未找到可用于图片图注的中文字体。"
            "请安装 Noto Sans CJK SC，或通过 `CJK_FONT_PATH` 指定字体文件。"
        )
    return ImageFont.truetype(resolved_path, size)


def _fit_caption(
    draw: ImageDraw.ImageDraw,
    caption: str,
    max_width: int,
    font_path: str | None = None,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    normalized = "".join(caption.split()).strip("。 ")
    for size in range(_CAPTION_MAX_FONT_SIZE, _CAPTION_MIN_FONT_SIZE - 1, -2):
        font = _load_caption_font(size, font_path)
        bounds = draw.textbbox((0, 0), normalized, font=font)
        if bounds[2] - bounds[0] <= max_width:
            return font, [normalized]

    font = _load_caption_font(_CAPTION_MIN_FONT_SIZE, font_path)
    candidates: list[tuple[int, int, int]] = []
    for split_index in range(1, len(normalized)):
        left_width = draw.textbbox((0, 0), normalized[:split_index], font=font)[2]
        right_width = draw.textbbox((0, 0), normalized[split_index:], font=font)[2]
        if left_width <= max_width and right_width <= max_width:
            candidates.append(
                (max(left_width, right_width), abs(left_width - right_width), split_index)
            )
    if not candidates:
        return font, [normalized]
    split_index = min(candidates)[2]
    return font, [normalized[:split_index], normalized[split_index:]]


def _draw_image_caption(
    canvas: Image.Image,
    caption: str,
    image_bounds: tuple[int, int, int, int],
    font_path: str | None = None,
) -> None:
    if not caption.strip():
        return

    left, top, right, bottom = image_bounds
    draw = ImageDraw.Draw(canvas, "RGBA")
    max_text_width = max(120, right - left - _CAPTION_IMAGE_MARGIN * 2)
    font, lines = _fit_caption(draw, caption, max_text_width, font_path)
    line_bounds = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_widths = [bounds[2] - bounds[0] for bounds in line_bounds]
    line_height = max(bounds[3] - bounds[1] for bounds in line_bounds)
    line_gap = 6
    text_height = line_height * len(lines) + line_gap * (len(lines) - 1)
    box_width = max(line_widths) + _CAPTION_HORIZONTAL_PADDING * 2
    box_height = text_height + _CAPTION_VERTICAL_PADDING * 2
    box_right = right - _CAPTION_IMAGE_MARGIN
    box_left = max(left, box_right - box_width)
    below_top = bottom + _CAPTION_GAP
    if below_top + box_height <= _SUBTITLE_SAFE_TOP:
        box_top = below_top
        box_bottom = box_top + box_height
    else:
        box_right = right - _CAPTION_IMAGE_MARGIN
        box_left = max(left + _CAPTION_IMAGE_MARGIN, box_right - box_width)
        box_bottom = bottom - _CAPTION_IMAGE_MARGIN
        box_top = max(top + _CAPTION_IMAGE_MARGIN, box_bottom - box_height)

    draw.rounded_rectangle(
        (box_left, box_top, box_right, box_bottom),
        radius=8,
        fill=(0, 0, 0, 170),
    )
    cursor_y = box_top + _CAPTION_VERTICAL_PADDING
    for line, line_width in zip(lines, line_widths):
        draw.text(
            (box_right - _CAPTION_HORIZONTAL_PADDING - line_width, cursor_y),
            line,
            font=font,
            fill=(255, 255, 255, 245),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 220),
        )
        cursor_y += line_height + line_gap


def _composite(
    img: Image.Image,
    caption: str = "",
    font_path: str | None = None,
) -> Image.Image:
    """Black vertical canvas with a centered, aspect-preserving image."""
    img_rgb = img.convert("RGB")
    fg_ratio = min(_W / img_rgb.width, _H / img_rgb.height)
    fg_w, fg_h = int(img_rgb.width * fg_ratio), int(img_rgb.height * fg_ratio)
    fg = img_rgb.resize((fg_w, fg_h), Image.LANCZOS)

    canvas = Image.new("RGB", (_W, _H), "black")
    fg_x = (_W - fg_w) // 2
    fg_y = (_H - fg_h) // 2
    canvas.paste(fg, (fg_x, fg_y))
    _draw_image_caption(
        canvas,
        caption,
        (fg_x, fg_y, fg_x + fg_w, fg_y + fg_h),
        font_path,
    )
    return canvas


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
    image_captions: list[str] | None = None,
    font_path: str | None = None,
) -> tuple[str, int]:
    """Render a black vertical slideshow with image-specific captions.

    Subtitle timing and styling are handled later by FFmpeg/libass. The
    image captions are rendered into frames and follow each image's bounds.
    """
    del srt_path, title, article_date, img_top, lead_in
    n = len(image_paths)
    captions = image_captions or [""] * n

    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for f in os.listdir(frames_dir):
        os.remove(os.path.join(frames_dir, f))

    img_cache: dict[tuple[str, str], Image.Image] = {}

    def get_base(path: str, caption: str) -> Image.Image:
        cache_key = (path, caption)
        if cache_key not in img_cache:
            with Image.open(path) as image:
                img_cache[cache_key] = _composite(image, caption, font_path)
        return img_cache[cache_key].copy()

    frame_interval = 1.0 / _FPS
    total = max(1, int(duration * _FPS) + 1)

    for i in range(total):
        t = i * frame_interval
        image_index = int(t / per_image) % n
        caption = captions[image_index] if image_index < len(captions) else ""
        frame = get_base(image_paths[image_index], caption)
        frame.save(os.path.join(frames_dir, f"{i:05d}.jpg"), "JPEG", quality=88)
        if i % 100 == 0:
            logger.info("Rendered frame %d/%d (t=%.1fs)", i + 1, total, t)

    logger.info("Rendered %d frames at %dfps", total, _FPS)
    return frames_dir, _FPS
