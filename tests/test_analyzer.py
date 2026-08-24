import json
from unittest.mock import MagicMock

import pytest

from src.analyzer import analyze_article
from src.models import AnalyzedArticle, ScrapedArticle


def _make_scraped(title="Arsenal Win", full_text="Match report content") -> ScrapedArticle:
    return ScrapedArticle(title=title, link="https://example.com/1", full_text=full_text)


def _valid_response() -> str:
    return json.dumps({
        "title_cn": "阿森纳胜利",
        "title_original": "Arsenal Win",
        "article_type": "赛后分析",
        "overview": "阿森纳在主场击败曼城。",
        "detail": "详细的比赛分析。",
        "key_people_and_data": "萨卡：2球",
        "impact": "阿森纳升至榜首",
        "link": "https://example.com/1",
    })


class TestAnalyzeArticle:
    def test_returns_analyzed_article(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _valid_response()

        result = analyze_article(_make_scraped(), mock_llm)

        assert isinstance(result, AnalyzedArticle)
        assert result.title_cn == "阿森纳胜利"

    def test_passes_title_and_text_to_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _valid_response()

        analyze_article(_make_scraped(title="City Lose", full_text="City lost badly"), mock_llm)

        _, user_arg = mock_llm.complete.call_args[0]
        assert "City Lose" in user_arg
        assert "City lost badly" in user_arg

    def test_requests_an_interesting_but_grounded_title(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _valid_response()

        analyze_article(_make_scraped(), mock_llm)

        system_prompt = mock_llm.complete.call_args.args[0]
        assert "想点开看看发生了什么" in system_prompt
        assert "新闻钩子" in system_prompt
        assert "吸引力必须来自原文事实" in system_prompt
        assert "不能夸大、虚构" in system_prompt

    def test_handles_json_wrapped_in_code_block(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = f"```json\n{_valid_response()}\n```"

        assert analyze_article(_make_scraped(), mock_llm).title_cn == "阿森纳胜利"

    def test_parses_response_with_raw_control_characters(self):
        mock_llm = MagicMock()
        response = json.loads(_valid_response())
        response["detail"] = "第一行\n第二行\t缩进"
        mock_llm.complete.return_value = json.dumps(
            response, ensure_ascii=False
        ).replace("\\n", "\n").replace("\\t", "\t")

        assert analyze_article(_make_scraped(), mock_llm).detail == "第一行\n第二行\t缩进"

    def test_raises_on_malformed_response(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "not json at all"

        with pytest.raises(ValueError, match="Failed to parse"):
            analyze_article(_make_scraped(), mock_llm)

    def test_normalizes_and_limits_douyin_title(self):
        mock_llm = MagicMock()
        response = json.loads(_valid_response())
        response["title_cn"] = "“#这是一个超过三十个字符而且需要被截断的中文封面标题用于测试”"
        mock_llm.complete.return_value = json.dumps(response, ensure_ascii=False)

        result = analyze_article(_make_scraped(), mock_llm)

        assert len(result.title_cn) <= 30
        assert "#" not in result.title_cn
        assert "“" not in result.title_cn

    def test_normalizes_structured_values_in_text_fields(self):
        mock_llm = MagicMock()
        response = json.loads(_valid_response())
        response["overview"] = ["阿森纳取胜。", "球队升至榜首。"]
        response["key_people_and_data"] = {
            "people": ["萨卡", "厄德高"],
            "data": ["2粒进球", "60%控球率"],
        }
        mock_llm.complete.return_value = json.dumps(response, ensure_ascii=False)

        result = analyze_article(_make_scraped(), mock_llm)

        assert result.overview == "阿森纳取胜。；球队升至榜首。"
        assert result.key_people_and_data == (
            "people：萨卡；厄德高；data：2粒进球；60%控球率"
        )

    def test_requires_all_content_fields(self):
        mock_llm = MagicMock()
        response = json.loads(_valid_response())
        del response["detail"]
        mock_llm.complete.return_value = json.dumps(response, ensure_ascii=False)

        with pytest.raises(ValueError, match="missing required fields"):
            analyze_article(_make_scraped(), mock_llm)
