import html
import logging
import os
import re

logger = logging.getLogger(__name__)

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FONT_NAME = "Noto Sans CJK SC"
FONT_SIZE = 62
MARGIN_LEFT = 50
MARGIN_RIGHT = 50
MARGIN_BOTTOM = 380
MAX_LINE_WIDTH = 18.0

_CJK_FONT_CANDIDATES = (
    "~/Library/Fonts/NotoSansCJKsc-Regular.otf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.otf",
)

_TIMESTAMP = r"\d{1,2}:\d{2}:\d{2}[,.]\d{3}|\d{1,2}:\d{2}[,.]\d{3}"
_CUE_RE = re.compile(
    rf"({_TIMESTAMP})\s*-->\s*({_TIMESTAMP})[^\n]*\n(.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)
_PROTECTED_RE = re.compile(
    r"(?:\d{4}年\d{1,2}月\d{1,2}日"
    r"|\d+(?:[.,]\d+)*(?:亿|万|千)?(?:[A-Za-z\u4e00-\u9fff%]+)"
    r"|[A-Za-z]+(?:[-'][A-Za-z]+)*)"
)
_PUNCTUATION_RE = re.compile(r"(?<=[，。！？；：、,.!?;:])")


def find_cjk_font() -> str | None:
    configured_path = os.environ.get("CJK_FONT_PATH")
    candidates = ((configured_path,) if configured_path else ()) + _CJK_FONT_CANDIDATES
    for candidate in candidates:
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return None


def _timestamp_to_seconds(timestamp: str) -> float:
    parts = timestamp.replace(",", ".").split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return int(parts[0]) * 60 + float(parts[1])


def _seconds_to_ass(timestamp: float) -> str:
    total_centiseconds = max(0, round(timestamp * 100))
    hours, remainder = divmod(total_centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def parse_vtt(path: str) -> list[tuple[float, float, str]]:
    with open(path, encoding="utf-8") as subtitle_file:
        content = subtitle_file.read().lstrip("\ufeff")

    entries: list[tuple[float, float, str]] = []
    for match in _CUE_RE.finditer(content):
        text = re.sub(r"<[^>]+>", "", match.group(3))
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        if text:
            entries.append(
                (
                    _timestamp_to_seconds(match.group(1)),
                    _timestamp_to_seconds(match.group(2)),
                    text,
                )
            )
    logger.info("Parsed %d subtitle entries from %s", len(entries), path)
    return entries


def _display_width(text: str) -> float:
    return sum(1.0 if ord(character) > 0x2E7F else 0.5 for character in text)


def _protect_tokens(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        marker = f"\ue000{len(protected)}\ue001"
        protected[marker] = match.group(0)
        return marker

    return _PROTECTED_RE.sub(replace, text), protected


def _restore_tokens(text: str, protected: dict[str, str]) -> str:
    for marker, original in protected.items():
        text = text.replace(marker, original)
    return text


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "\ue000":
            end = text.find("\ue001", index) + 1
            tokens.append(text[index:end])
            index = end
            continue
        if text[index].isspace():
            index += 1
            continue
        if text[index].isascii() and text[index].isalnum():
            end = index + 1
            while end < len(text) and (text[end].isascii() and (text[end].isalnum() or text[end] in "-'")):
                end += 1
            tokens.append(text[index:end])
            index = end
            continue
        tokens.append(text[index])
        index += 1
    return tokens


def _hard_wrap(text: str, max_width: float, protected: dict[str, str]) -> list[str]:
    lines: list[str] = []
    current = ""
    current_width = 0.0
    for token in _tokenize(text):
        token_width = _display_width(protected.get(token, token))
        if current and current_width + token_width > max_width:
            lines.append(current)
            current = token
            current_width = token_width
        else:
            current += token
            current_width += token_width
    if current:
        lines.append(current)
    return lines


def _wrapped_lines(text: str, max_width: float) -> list[str]:
    protected_text, protected = _protect_tokens(text.strip())
    segments = [segment.strip() for segment in _PUNCTUATION_RE.split(protected_text) if segment.strip()]
    lines: list[str] = []
    for segment in segments:
        lines.extend(_hard_wrap(segment, max_width, protected))
    return [_restore_tokens(line, protected) for line in lines]


def split_subtitle_text(text: str, max_width: float = MAX_LINE_WIDTH) -> str:
    lines = _wrapped_lines(text, max_width)
    return "\\N".join(lines[:2])


def _subtitle_chunks(text: str, max_width: float = MAX_LINE_WIDTH) -> list[str]:
    lines = _wrapped_lines(text, max_width)
    return ["\\N".join(lines[index:index + 2]) for index in range(0, len(lines), 2)]


def _chunk_width(text: str) -> float:
    return max(_display_width(text.replace("\\N", "")), 1.0)


def _escape_ass_text(text: str) -> str:
    return text.replace("{", "\\{").replace("}", "\\}")


def _ass_header(font_name: str = FONT_NAME) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chinese,{font_name},{FONT_SIZE},&H0000FFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,4,0,2,{MARGIN_LEFT},{MARGIN_RIGHT},{MARGIN_BOTTOM},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass_from_vtt(
    vtt_path: str,
    output_path: str,
    font_name: str = FONT_NAME,
) -> str:
    entries = parse_vtt(vtt_path)
    events = []
    for start, end, text in entries:
        chunks = _subtitle_chunks(text)
        if not chunks:
            continue
        total_width = sum(_chunk_width(chunk) for chunk in chunks)
        cue_duration = end - start
        cursor = start
        for index, chunk in enumerate(chunks):
            if index == len(chunks) - 1:
                chunk_end = end
            else:
                chunk_end = cursor + cue_duration * _chunk_width(chunk) / total_width
            events.append(
                "Dialogue: 0,{start},{end},Chinese,,0,0,0,,{text}".format(
                    start=_seconds_to_ass(cursor),
                    end=_seconds_to_ass(chunk_end),
                    text=_escape_ass_text(chunk),
                )
            )
            cursor = chunk_end

    with open(output_path, "w", encoding="utf-8") as ass_file:
        ass_file.write(_ass_header(font_name))
        ass_file.write("\n".join(events))
        ass_file.write("\n")
    logger.info("Wrote %d ASS subtitle events to %s", len(events), output_path)
    return output_path
