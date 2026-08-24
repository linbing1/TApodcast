import json

from src.publish_copy import generate_publish_copy


class StubLLM:
    def __init__(self, response: dict):
        self.response = response
        self.calls = []

    def complete(self, system, user, json_mode=False, **kwargs):
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
    assert result["hashtags"] == ["英超", "利物浦", "足球商业", "足球新闻", "足球"]
    assert result["description_with_hashtags"].endswith(
        "#英超 #利物浦 #足球商业 #足球新闻 #足球"
    )
    assert (tmp_path / "title.txt").read_text(encoding="utf-8") == cover_title
    assert (tmp_path / "publish_title.txt").read_text(encoding="utf-8") == cover_title
    assert (tmp_path / "publish_description.txt").read_text(
        encoding="utf-8"
    ) == result["description_with_hashtags"]
    saved = json.loads((tmp_path / "publish.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == 1
    assert {key: value for key, value in saved.items() if key != "schema_version"} == result

    request = json.loads(llm.calls[0][1])
    assert request["cover_title"] == cover_title
    assert llm.calls[0][2] is True


def test_generate_publish_copy_defaults_to_local_generation(tmp_path):
    _write_article_outputs(tmp_path)

    result = generate_publish_copy(str(tmp_path))

    assert result["title"] == "利物浦为何吸引超级富豪入股"
    assert result["description"] == "利物浦正在评估少数股权投资。"
    assert result["hashtags"] == ["利物浦", "足球商业", "英超", "足球新闻", "足球"]


def test_local_hashtags_include_related_teams_for_discovery(tmp_path):
    _write_article_outputs(tmp_path, "曼城补时逆转伯恩茅斯")
    (tmp_path / "page.json").write_text(
        json.dumps({
            "title": "Man City vs Bournemouth takeaways",
            "main_text": "Article content",
        }),
        encoding="utf-8",
    )
    (tmp_path / "analysis.json").write_text(
        json.dumps({
            "title_cn": "曼城补时逆转伯恩茅斯",
            "article_type": "赛后分析",
            "overview": "曼城在英超首战中逆转伯恩茅斯。",
            "detail": "球队上周末还对阵阿森纳。",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "script.txt").write_text(
        "曼城补时逆转伯恩茅斯，阿森纳是近期对手。",
        encoding="utf-8",
    )

    result = generate_publish_copy(str(tmp_path))

    assert result["hashtags"] == [
        "曼城",
        "伯恩茅斯",
        "比赛分析",
        "英超",
        "足球新闻",
        "阿森纳",
    ]


def test_local_hashtags_add_broad_topics_and_secondary_clubs(tmp_path):
    _write_article_outputs(tmp_path, "曼联为何被赫尔城拆解")
    (tmp_path / "page.json").write_text(
        json.dumps({
            "title": "Hull City expose Manchester United tactical problems",
            "main_text": "Article content",
        }),
        encoding="utf-8",
    )
    (tmp_path / "analysis.json").write_text(
        json.dumps({
            "title_cn": "曼联为何被赫尔城拆解",
            "article_type": "战术解读",
            "overview": "赫尔城用5-4-1低位防守限制曼联。",
            "detail": "文章同时对比了曼城的逼抢和切尔西的阵地战。",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "script.txt").write_text(
        "赫尔城用低位防守限制曼联，并对比曼城和切尔西的战术。",
        encoding="utf-8",
    )

    result = generate_publish_copy(str(tmp_path))

    assert result["hashtags"] == [
        "曼联",
        "赫尔城",
        "英超战术",
        "英超",
        "足球新闻",
        "曼城",
        "切尔西",
    ]


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
    assert result["description_with_hashtags"].endswith(
        "#英超 #切尔西 #足球新闻 #利物浦 #足球商业 #足球"
    )


def test_generate_publish_copy_fills_missing_hashtags(tmp_path):
    _write_article_outputs(tmp_path)
    llm = StubLLM({
        "title": "unused",
        "description": "作品简介",
        "hashtags": ["英超", "利物浦"],
    })

    result = generate_publish_copy(str(tmp_path), llm)

    assert result["hashtags"] == ["英超", "利物浦", "足球商业", "足球新闻", "足球"]


def test_generate_publish_copy_limits_hashtags_to_ten(tmp_path):
    _write_article_outputs(tmp_path)
    llm = StubLLM({
        "title": "unused",
        "description": "作品简介",
        "hashtags": [f"话题{index}" for index in range(12)],
    })

    result = generate_publish_copy(str(tmp_path), llm)

    assert result["hashtags"] == [f"话题{index}" for index in range(10)]
