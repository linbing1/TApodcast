import logging
import re
from pathlib import Path

from src.artifacts import (
    load_image_caption_manifest,
    load_image_manifest,
    write_artifact,
)
from src.models import ImageCaptionManifest, ImageCaptionRecord, ImageRecord

logger = logging.getLogger(__name__)

_CREDIT_SUFFIX_RE = re.compile(
    r"\s*[（(]([^()（）]*(?:Getty|Images|Reuters|AP|AFP|PA|Imagn|The Athletic)"
    r"[^()（）]*)[）)]\s*$",
    re.IGNORECASE,
)


def _normalize_caption(text: object) -> str:
    return " ".join(str(text or "").split()).strip("。 ")


def _strip_credit(text: object) -> str:
    return _CREDIT_SUFFIX_RE.sub("", _normalize_caption(text)).strip()


def _caption_source(record: ImageRecord) -> str:
    return _strip_credit(record.caption or record.alt)


def _local_caption(text: str) -> str:
    """Keep existing Chinese captions without adding an LLM translation call."""
    return text if re.search(r"[\u3400-\u9fff]", text) else ""


def generate_image_captions(output_dir: str) -> list[dict[str, str]]:
    manifest_path = Path(output_dir) / "images.json"
    output_path = Path(output_dir) / "image_captions.json"
    if not manifest_path.exists():
        logger.info("No image manifest found; skipping image captions: %s", manifest_path)
        return []

    records = load_image_manifest(manifest_path).images

    output_records: list[ImageCaptionRecord] = []
    for index, record in enumerate(records):
        if record.status != "downloaded":
            continue
        original = _caption_source(record)
        output_record = ImageCaptionRecord(
            local_path=record.local_path or f"images/{index:03d}.jpg",
            caption_original=original,
            caption_cn=_local_caption(original),
        )
        output_records.append(output_record)

    write_artifact(
        output_path,
        ImageCaptionManifest(captions=output_records),
    )
    captioned_count = sum(bool(record.caption_cn) for record in output_records)
    logger.info(
        "Prepared %d/%d local Chinese image captions: %s",
        captioned_count,
        len(output_records),
        output_path,
    )
    return [record.model_dump() for record in output_records]


def load_image_captions(output_dir: str, image_paths: list[str]) -> list[str]:
    captions_path = Path(output_dir) / "image_captions.json"
    if not captions_path.exists():
        return [""] * len(image_paths)

    try:
        records = load_image_caption_manifest(captions_path).captions
    except ValueError:
        logger.warning("Ignoring invalid image captions file: %s", captions_path)
        return [""] * len(image_paths)

    by_name = {
        Path(record.local_path).name: _normalize_caption(record.caption_cn)
        for record in records
        if record.local_path
    }
    return [by_name.get(Path(path).name, "") for path in image_paths]
