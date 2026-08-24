import json

from src.image_captioner import generate_image_captions, load_image_captions


def test_generate_and_load_image_captions_preserves_image_mapping(tmp_path):
    (tmp_path / "images.json").write_text(json.dumps([
        {
            "local_path": "images/000.jpg",
            "status": "downloaded",
            "caption": "Liverpool owner John W Henry and his wife Linda with the trophy "
                       "(Michael Regan/Getty Images)",
            "alt": "",
        },
        {
            "local_path": "images/001.jpg",
            "status": "failed",
            "caption": "Skipped image",
            "alt": "",
        },
        {
            "local_path": "images/002.jpg",
            "status": "downloaded",
            "caption": "Jeff Bezos founded Amazon from his garage in 1994",
            "alt": "",
        },
    ]), encoding="utf-8")
    records = generate_image_captions(str(tmp_path))

    assert records == [
        {
            "local_path": "images/000.jpg",
            "caption_original": "Liverpool owner John W Henry and his wife Linda with the trophy",
            "caption_cn": "",
        },
        {
            "local_path": "images/002.jpg",
            "caption_original": "Jeff Bezos founded Amazon from his garage in 1994",
            "caption_cn": "",
        },
    ]
    assert load_image_captions(
        str(tmp_path),
        [str(tmp_path / "images/000.jpg"), str(tmp_path / "images/002.jpg")],
    ) == ["", ""]


def test_generate_image_captions_uses_alt_when_caption_is_missing(tmp_path):
    (tmp_path / "images.json").write_text(json.dumps([
        {
            "local_path": "images/000.jpg",
            "status": "downloaded",
            "caption": "",
            "alt": "Cole Palmer trains with Chelsea in Hong Kong",
        },
    ]), encoding="utf-8")
    records = generate_image_captions(str(tmp_path))

    assert records[0]["caption_original"] == (
        "Cole Palmer trains with Chelsea in Hong Kong"
    )


def test_generate_image_captions_keeps_existing_chinese_caption_locally(tmp_path):
    (tmp_path / "images.json").write_text(json.dumps([
        {
            "local_path": "images/000.jpg",
            "status": "downloaded",
            "caption": "帕尔默在训练中（Getty Images）",
            "alt": "",
        },
    ]), encoding="utf-8")

    records = generate_image_captions(str(tmp_path))

    assert records[0]["caption_original"] == "帕尔默在训练中"
    assert records[0]["caption_cn"] == "帕尔默在训练中"


def test_load_image_captions_returns_blanks_for_invalid_file(tmp_path):
    (tmp_path / "image_captions.json").write_text(
        json.dumps({"captions": []}),
        encoding="utf-8",
    )

    assert load_image_captions(
        str(tmp_path),
        [str(tmp_path / "images/000.jpg"), str(tmp_path / "images/001.jpg")],
    ) == ["", ""]
