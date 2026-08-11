import logging
import os

from PIL import Image

logger = logging.getLogger(__name__)

_W, _H = 1080, 1920
_FPS = 5  # subtitle granularity; ffmpeg will upsample to 30fps

def _composite(img: Image.Image) -> Image.Image:
    """Black vertical canvas with a centered, aspect-preserving image."""
    img_rgb = img.convert("RGB")
    fg_ratio = min(_W / img_rgb.width, _H / img_rgb.height)
    fg_w, fg_h = int(img_rgb.width * fg_ratio), int(img_rgb.height * fg_ratio)
    fg = img_rgb.resize((fg_w, fg_h), Image.LANCZOS)

    canvas = Image.new("RGB", (_W, _H), "black")
    canvas.paste(fg, ((_W - fg_w) // 2, (_H - fg_h) // 2))
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
) -> tuple[str, int]:
    """Render a black vertical slideshow without text overlays.

    Subtitle timing and styling are handled later by FFmpeg/libass. The
    retained text-related arguments keep this function compatible with the
    earlier pipeline API.
    """
    del srt_path, title, article_date, img_top, lead_in
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

    for i in range(total):
        t = i * frame_interval
        frame = get_base(image_paths[int(t / per_image) % n])
        frame.save(os.path.join(frames_dir, f"{i:05d}.jpg"), "JPEG", quality=88)
        if i % 100 == 0:
            logger.info("Rendered frame %d/%d (t=%.1fs)", i + 1, total, t)

    logger.info("Rendered %d frames at %dfps", total, _FPS)
    return frames_dir, _FPS
