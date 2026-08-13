import json
import logging
import re
from pathlib import Path

from src.llm import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一位中文体育短视频编辑。请把图片说明翻译并精简成适合视频画面展示的中文图注。

要求：
- 准确保留人物、球队、事件和年份等关键信息；
- 不添加原文没有的信息；
- 删除摄影师、图片机构、版权和来源信息；
- 使用自然、简洁的中文新闻表达，避免生硬直译；
- 每条尽量控制在12至24个汉字，优先保证单行展示；
- 可省略不影响画面理解的身份修饰，但不得省略核心人物或事件；
- 不使用句号结尾；
- 仅返回 JSON 对象，格式为 {"captions":[{"index":0,"caption_cn":"..."}]}。"""

_CREDIT_SUFFIX_RE = re.compile(
    r"\s*[（(]([^()（）]*(?:Getty|Images|Reuters|AP|AFP|PA|Imagn|The Athletic)"
    r"[^()（）]*)[）)]\s*$",
    re.IGNORECASE,
)


def _normalize_caption(text: object) -> str:
    return " ".join(str(text or "").split()).strip("。 ")


def _strip_credit(text: object) -> str:
    return _CREDIT_SUFFIX_RE.sub("", _normalize_caption(text)).strip()


def _caption_source(record: dict) -> str:
    return _strip_credit(record.get("caption") or record.get("alt"))


def _parse_response(response: str) -> dict[int, str]:
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    data = json.loads(text.strip())
    items = data.get("captions", []) if isinstance(data, dict) else []
    translated: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item["index"])
        except (KeyError, TypeError, ValueError):
            continue
        caption = _normalize_caption(item.get("caption_cn"))
        if caption:
            translated[index] = caption
    return translated


def generate_image_captions(output_dir: str, llm: LLMClient) -> list[dict[str, str]]:
    manifest_path = Path(output_dir) / "images.json"
    output_path = Path(output_dir) / "image_captions.json"
    if not manifest_path.exists():
        logger.info("No image manifest found; skipping image captions: %s", manifest_path)
        return []

    records = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"Image manifest must contain a JSON array: {manifest_path}")

    output_records: list[dict[str, str]] = []
    output_by_index: dict[int, dict[str, str]] = {}
    candidates: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        if record.get("status") not in (None, "downloaded"):
            continue
        original = _caption_source(record)
        output_record = {
            "local_path": record.get("local_path", f"images/{index:03d}.jpg"),
            "caption_original": original,
            "caption_cn": "",
        }
        output_records.append(output_record)
        output_by_index[index] = output_record
        if original:
            candidates.append({"index": index, "caption": original})

    if candidates:
        response = llm.complete(
            _SYSTEM_PROMPT,
            json.dumps({"images": candidates}, ensure_ascii=False),
            json_mode=True,
        )
        translated = _parse_response(response)
        for index, caption in translated.items():
            if index in output_by_index:
                output_by_index[index]["caption_cn"] = caption

    output_path.write_text(
        json.dumps(output_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    translated_count = sum(bool(record["caption_cn"]) for record in output_records)
    logger.info(
        "Generated %d/%d Chinese image captions: %s",
        translated_count,
        len(output_records),
        output_path,
    )
    return output_records


def load_image_captions(output_dir: str, image_paths: list[str]) -> list[str]:
    captions_path = Path(output_dir) / "image_captions.json"
    if not captions_path.exists():
        return [""] * len(image_paths)

    records = json.loads(captions_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        logger.warning("Ignoring invalid image captions file: %s", captions_path)
        return [""] * len(image_paths)

    by_name = {
        Path(record.get("local_path", "")).name: _normalize_caption(
            record.get("caption_cn")
        )
        for record in records
        if isinstance(record, dict) and record.get("local_path")
    }
    return [by_name.get(Path(path).name, "") for path in image_paths]
