import json

from src.image_captioner import generate_image_captions, load_image_captions


class StubLLM:
    def __init__(self):
        self.calls = []

    def complete(self, system, user, json_mode=False):
        self.calls.append((system, user, json_mode))
        return json.dumps({
            "captions": [
                {"index": 0, "caption_cn": "亨利夫妇手捧英超冠军奖杯。"},
                {"index": 2, "caption_cn": "贝索斯于1994年创办亚马逊"},
            ]
        }, ensure_ascii=False)


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
    llm = StubLLM()

    records = generate_image_captions(str(tmp_path), llm)

    assert records == [
        {
            "local_path": "images/000.jpg",
            "caption_original": "Liverpool owner John W Henry and his wife Linda with the trophy",
            "caption_cn": "亨利夫妇手捧英超冠军奖杯",
        },
        {
            "local_path": "images/002.jpg",
            "caption_original": "Jeff Bezos founded Amazon from his garage in 1994",
            "caption_cn": "贝索斯于1994年创办亚马逊",
        },
    ]
    assert llm.calls[0][2] is True
    assert load_image_captions(
        str(tmp_path),
        [str(tmp_path / "images/000.jpg"), str(tmp_path / "images/002.jpg")],
    ) == ["亨利夫妇手捧英超冠军奖杯", "贝索斯于1994年创办亚马逊"]


def test_generate_image_captions_uses_alt_when_caption_is_missing(tmp_path):
    (tmp_path / "images.json").write_text(json.dumps([
        {
            "local_path": "images/000.jpg",
            "status": "downloaded",
            "caption": "",
            "alt": "Cole Palmer trains with Chelsea in Hong Kong",
        },
    ]), encoding="utf-8")
    llm = StubLLM()

    records = generate_image_captions(str(tmp_path), llm)

    assert records[0]["caption_original"] == (
        "Cole Palmer trains with Chelsea in Hong Kong"
    )
    request = json.loads(llm.calls[0][1])
    assert request == {
        "images": [{
            "index": 0,
            "caption": "Cole Palmer trains with Chelsea in Hong Kong",
        }]
    }


def test_load_image_captions_returns_blanks_for_invalid_file(tmp_path):
    (tmp_path / "image_captions.json").write_text(
        json.dumps({"captions": []}),
        encoding="utf-8",
    )

    assert load_image_captions(
        str(tmp_path),
        [str(tmp_path / "images/000.jpg"), str(tmp_path / "images/001.jpg")],
    ) == ["", ""]
