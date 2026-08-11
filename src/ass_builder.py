import logging
import re

logger = logging.getLogger(__name__)

_VIDEO_H = 1920
_VIDEO_W = 1080
_WHITE = "&H00FFFFFF"
_BLACK_OUTLINE = "&H00000000"
_TRANSPARENT = "&H00000000"

_MAX_CHARS = 24

_FULLWIDTH_TABLE = str.maketrans("，。！？；：（）、《》【】", ",.!?;:(),<>[]")


def _to_halfwidth(text: str) -> str:
    return text.replace("……", "...").replace("——", "--").translate(_FULLWIDTH_TABLE)


def _wrap(text: str, max_chars: int = _MAX_CHARS) -> str:
    """Pre-wrap text with ASS line breaks; CJK chars count as 1, ASCII as 0.5."""
    lines: list[str] = []
    current = ""
    width = 0.0
    for ch in text:
        w = 1.0 if ord(ch) > 0x2E7F else 0.5
        if width + w > max_chars and current:
            lines.append(current)
            current = ch
            width = w
        else:
            current += ch
            width += w
    if current:
        lines.append(current)
    return "\\N".join(lines)


def _ts_to_sec(ts: str) -> float:
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return int(parts[0]) * 60 + float(parts[1])


def _sec_to_ass(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{int(s):02d}.{int((s % 1) * 100):02d}"


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
    logger.info("Parsed %d subtitle entries from %s", len(entries), path)
    return entries


def _ass_header(title_margin_v: int, sub_margin_v: int) -> str:
    return f"""\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,PingFang SC,56,{_WHITE},&H000000FF,{_BLACK_OUTLINE},{_TRANSPARENT},-1,0,0,0,100,100,2,0,1,3,0,2,30,30,{title_margin_v},1
Style: Date,PingFang SC,48,{_WHITE},&H000000FF,{_BLACK_OUTLINE},{_TRANSPARENT},0,0,0,0,100,100,2,0,1,3,0,2,30,30,{title_margin_v},1
Style: Default,PingFang SC,48,{_WHITE},&H000000FF,{_BLACK_OUTLINE},{_TRANSPARENT},0,0,0,0,100,100,2,0,1,3,0,8,30,30,{sub_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(
    srt_path: str,
    title: str,
    date_str: str,
    duration: float,
    output_path: str,
    img_top: int = 600,
    lead_in: float = 0.0,
) -> str:
    subtitles = _parse_subtitles(srt_path)
    end_time = _sec_to_ass(duration + 3)

    title_bottom_y = img_top - 80
    sub_top_y = _VIDEO_H - img_top + 80

    header = _ass_header(
        title_margin_v=_VIDEO_H - title_bottom_y,
        sub_margin_v=sub_top_y,
    )

    events: list[str] = []

    _LINE_H = 72
    _DATE_GAP = 24
    if title:
        wrapped_lines = _wrap(_to_halfwidth(title), max_chars=13).split("\\N")[:2]
        title_text = "\\N".join(wrapped_lines)
        if date_str:
            events.append(
                f"Dialogue: 0,0:00:00.00,{end_time},Date,,0,0,0,"
                f",{{\\an2\\pos(540,{title_bottom_y})}}{date_str}"
            )
        title_event_y = title_bottom_y - _LINE_H - _DATE_GAP
        events.append(
            f"Dialogue: 0,0:00:00.00,{end_time},Title,,0,0,0,"
            f",{{\\an2\\pos(540,{title_event_y})}}{title_text}"
        )

    for start, end, text in subtitles:
        events.append(
            f"Dialogue: 0,{_sec_to_ass(start + lead_in)},{_sec_to_ass(end + lead_in)},Default,,0,0,0,"
            f",{{\\an8}}{_wrap(_to_halfwidth(text))}"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events))
        f.write("\n")

    return output_path
