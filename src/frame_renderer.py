import logging
import os

from PIL import Image, ImageDraw, ImageFont

from src.subtitle_renderer import find_cjk_font

logger = logging.getLogger(__name__)

_W, _H = 1080, 1920
_FPS = 15
_KEN_BURNS_START_ZOOM = 1.0
_KEN_BURNS_END_ZOOM = 1.08
_KEN_BURNS_PAN_PIXELS = 14
_IMAGE_TRANSITION_SECONDS = 0.3
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
    caption_layout: tuple[ImageFont.FreeTypeFont, list[str]] | None = None,
) -> None:
    if not caption.strip():
        return

    left, top, right, bottom = image_bounds
    left = max(0, left)
    top = max(0, top)
    right = min(_W, right)
    bottom = min(_H, bottom)
    if right <= left or bottom <= top:
        return
    draw = ImageDraw.Draw(canvas, "RGBA")
    max_text_width = max(120, right - left - _CAPTION_IMAGE_MARGIN * 2)
    font, lines = caption_layout or _fit_caption(
        draw, caption, max_text_width, font_path
    )
    line_bounds = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_widths = [bounds[2] - bounds[0] for bounds in line_bounds]
    line_heights = [bounds[3] - bounds[1] for bounds in line_bounds]
    line_gap = 6
    text_height = sum(line_heights) + line_gap * (len(lines) - 1)
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
    line_top = box_top + _CAPTION_VERTICAL_PADDING
    for line, line_bounds_item, line_width, line_height in zip(
        lines, line_bounds, line_widths, line_heights
    ):
        text_x = box_right - _CAPTION_HORIZONTAL_PADDING - line_bounds_item[2]
        text_y = line_top - line_bounds_item[1]
        draw.text(
            (text_x, text_y),
            line,
            font=font,
            fill=(255, 255, 255, 245),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 220),
        )
        line_top += line_height + line_gap


def _clamp_image_bounds(
    image_bounds: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    left, top, right, bottom = image_bounds
    return (
        max(0, left),
        max(0, top),
        min(_W, right),
        min(_H, bottom),
    )


def _ease_in_out(progress: float) -> float:
    progress = max(0.0, min(1.0, progress))
    return progress * progress * (3.0 - 2.0 * progress)


def _image_geometry(
    image_width: int,
    image_height: int,
    progress: float,
    motion_index: int,
) -> tuple[int, int, int, int]:
    base_ratio = min(_W / image_width, _H / image_height)
    base_width = int(image_width * base_ratio)
    base_height = int(image_height * base_ratio)
    eased = _ease_in_out(progress)
    zoom = _KEN_BURNS_START_ZOOM + (
        _KEN_BURNS_END_ZOOM - _KEN_BURNS_START_ZOOM
    ) * eased
    fg_width = int(base_width * zoom)
    fg_height = int(base_height * zoom)

    if image_width >= image_height:
        direction = 1 if motion_index % 2 == 0 else -1
        pan_x = int(direction * _KEN_BURNS_PAN_PIXELS * eased)
        pan_y = 0
    else:
        direction = 1 if motion_index % 2 == 0 else -1
        pan_x = 0
        pan_y = int(direction * _KEN_BURNS_PAN_PIXELS * eased)

    fg_x = (_W - fg_width) // 2 + pan_x
    fg_y = (_H - fg_height) // 2 + pan_y
    return fg_x, fg_y, fg_x + fg_width, fg_y + fg_height


def _composite(
    img: Image.Image,
    caption: str = "",
    font_path: str | None = None,
    progress: float = 0.0,
    motion_index: int = 0,
    caption_layout: tuple[ImageFont.FreeTypeFont, list[str]] | None = None,
    caption_bounds: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    """Render one Ken Burns frame on a black vertical canvas."""
    img_rgb = img.convert("RGB")
    fg_x, fg_y, fg_right, fg_bottom = _image_geometry(
        img_rgb.width,
        img_rgb.height,
        progress,
        motion_index,
    )
    fg_w = fg_right - fg_x
    fg_h = fg_bottom - fg_y
    fg = img_rgb.resize((fg_w, fg_h), Image.LANCZOS)

    canvas = Image.new("RGB", (_W, _H), "black")
    canvas.paste(fg, (fg_x, fg_y))
    _draw_image_caption(
        canvas,
        caption,
        caption_bounds or (fg_x, fg_y, fg_right, fg_bottom),
        font_path,
        caption_layout,
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
    image captions use a fixed layout based on each image's initial bounds;
    the image itself can continue moving underneath the caption.
    """
    del srt_path, title, article_date, img_top, lead_in
    n = len(image_paths)
    if n == 0:
        raise ValueError("At least one image is required to render frames")
    if per_image <= 0:
        raise ValueError("per_image must be greater than zero")
    captions = image_captions or [""] * n

    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for f in os.listdir(frames_dir):
        os.remove(os.path.join(frames_dir, f))

    img_cache: dict[str, Image.Image] = {}
    caption_bounds_cache: dict[int, tuple[int, int, int, int]] = {}
    caption_layout_cache: dict[
        int, tuple[ImageFont.FreeTypeFont, list[str]]
    ] = {}

    def get_image(path: str) -> Image.Image:
        if path not in img_cache:
            with Image.open(path) as image:
                img_cache[path] = image.convert("RGB")
        return img_cache[path]

    def get_caption_layout(
        image_index: int,
        image: Image.Image,
        caption: str,
    ) -> tuple[
        tuple[int, int, int, int] | None,
        tuple[ImageFont.FreeTypeFont, list[str]] | None,
    ]:
        if not caption.strip():
            return None, None

        if image_index not in caption_bounds_cache:
            caption_bounds_cache[image_index] = _clamp_image_bounds(
                _image_geometry(image.width, image.height, 0.0, image_index)
            )
        image_bounds = caption_bounds_cache[image_index]
        left, top, right, bottom = image_bounds
        max_text_width = max(120, right - left - _CAPTION_IMAGE_MARGIN * 2)
        if image_index not in caption_layout_cache:
            probe = ImageDraw.Draw(Image.new("RGB", (_W, _H)))
            caption_layout_cache[image_index] = _fit_caption(
                probe,
                caption,
                max_text_width,
                font_path,
            )
        return image_bounds, caption_layout_cache[image_index]

    def render_image_frame(index: int, progress: float) -> Image.Image:
        image = get_image(image_paths[index])
        caption = captions[index] if index < len(captions) else ""
        caption_bounds, layout = get_caption_layout(index, image, caption)
        return _composite(
            image,
            caption,
            font_path,
            progress,
            index,
            layout,
            caption_bounds,
        )

    frame_interval = 1.0 / _FPS
    total = max(1, int(duration * _FPS) + 1)

    for i in range(total):
        t = i * frame_interval
        image_position = t / per_image
        sequence_index = int(image_position)
        image_index = sequence_index % n
        image_progress = image_position - sequence_index
        transition_progress = (
            (t - sequence_index * per_image) / _IMAGE_TRANSITION_SECONDS
            if _IMAGE_TRANSITION_SECONDS > 0
            else 1.0
        )
        if sequence_index > 0 and transition_progress < 1.0:
            previous_index = (image_index - 1) % n
            outgoing = render_image_frame(previous_index, 1.0)
            incoming = render_image_frame(
                image_index,
                image_progress,
            )
            frame = Image.blend(
                outgoing,
                incoming,
                max(0.0, min(1.0, transition_progress)),
            )
        else:
            frame = render_image_frame(image_index, image_progress)
        frame.save(os.path.join(frames_dir, f"{i:05d}.jpg"), "JPEG", quality=88)
        if i % 100 == 0:
            logger.info("Rendered frame %d/%d (t=%.1fs)", i + 1, total, t)

    logger.info(
        "Rendered %d intermediate frames at %dfps (final video is encoded at 30fps)",
        total, _FPS,
    )
    return frames_dir, _FPS
