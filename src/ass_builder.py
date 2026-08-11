"""Compatibility wrapper for the consolidated VTT-to-ASS renderer."""

from src.subtitle_renderer import write_ass_from_vtt


def build_ass(
    srt_path: str,
    title: str,
    date_str: str,
    duration: float,
    output_path: str,
    img_top: int = 600,
    lead_in: float = 0.0,
) -> str:
    del title, date_str, duration, img_top, lead_in
    return write_ass_from_vtt(srt_path, output_path)
