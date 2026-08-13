import json

from src.publish_copy import generate_publish_copy


class StubLLM:
    def __init__(self, response: dict):
        self.response = response
        self.calls = []

    def complete(self, system, user, json_mode=False):
        self.calls.append((system, user, json_mode))
        return json.dumps(self.response, ensure_ascii=False)


def _write_article_outputs(tmp_path, title="利物浦为何吸引超级富豪入股"):
    (tmp_path / "title.txt").write_text(title, encoding="utf-8")
    (tmp_path / "page.json").write_text(
        json.dumps({
            "title": "Liverpool minority investment explained",
            "main_text": "Article content",
        }),
        encoding="utf-8",
    )
    (tmp_path / "analysis.json").write_text(
        json.dumps({
            "title_cn": title,
            "overview": "利物浦正在评估少数股权投资。",
            "detail": "多位富豪可能参与投资。",
            "key_people_and_data": "约翰·亨利、杰夫·贝索斯",
            "impact": "不会改变芬威体育集团的控股地位。",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "script.txt").write_text(
        "利物浦为什么会成为超级富豪眼中的热门投资标的？",
        encoding="utf-8",
    )


def test_generate_publish_copy_reuses_cover_title_and_writes_outputs(tmp_path):
    cover_title = "利物浦为何吸引超级富豪入股"
    _write_article_outputs(tmp_path, cover_title)
    llm = StubLLM({
        "title": "LLM不应覆盖封面标题",
        "description": "芬威体育集团考虑引入少数股权投资者，利物浦为何受到超级富豪关注？本期梳理潜在投资者、交易方式以及对俱乐部控制权的影响。",
        "hashtags": ["#英超", "利物浦", "足球商业", "英超"],
    })

    result = generate_publish_copy(str(tmp_path), llm)

    assert result["title"] == cover_title
    assert result["hashtags"] == ["英超", "利物浦", "足球商业"]
    assert result["description_with_hashtags"].endswith(
        "#英超 #利物浦 #足球商业"
    )
    assert (tmp_path / "title.txt").read_text(encoding="utf-8") == cover_title
    assert (tmp_path / "publish_title.txt").read_text(encoding="utf-8") == cover_title
    assert (tmp_path / "publish_description.txt").read_text(
        encoding="utf-8"
    ) == result["description_with_hashtags"]
    assert json.loads((tmp_path / "publish.json").read_text(encoding="utf-8")) == result

    request = json.loads(llm.calls[0][1])
    assert request["cover_title"] == cover_title
    assert llm.calls[0][2] is True


def test_generate_publish_copy_limits_title_and_total_description(tmp_path):
    _write_article_outputs(tmp_path, "这是一个超过三十个字符而且需要被严格截断的中文封面标题用于测试一致性")
    llm = StubLLM({
        "title": "unused",
        "description": "简介" * 600,
        "hashtags": ["英超", "切尔西", "足球新闻"],
    })

    result = generate_publish_copy(str(tmp_path), llm)

    assert len(result["title"]) == 30
    assert len(result["description_with_hashtags"]) <= 1000
    assert result["description_with_hashtags"].endswith("#英超 #切尔西 #足球新闻")


def test_generate_publish_copy_fills_missing_hashtags(tmp_path):
    _write_article_outputs(tmp_path)
    llm = StubLLM({
        "title": "unused",
        "description": "作品简介",
        "hashtags": ["英超", "利物浦"],
    })

    result = generate_publish_copy(str(tmp_path), llm)

    assert result["hashtags"] == ["英超", "利物浦", "足球新闻"]
