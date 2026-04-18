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
        "importance": 4,
        "overview": "阿森纳在主场击败曼城。",
        "detail": "详细的比赛分析...",
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
        assert result.importance == 4

    def test_passes_title_and_text_to_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _valid_response()
        article = _make_scraped(title="City Lose", full_text="City lost badly")
        analyze_article(article, mock_llm)
        _, user_arg = mock_llm.complete.call_args[0]
        assert "City Lose" in user_arg
        assert "City lost badly" in user_arg

    def test_handles_json_wrapped_in_code_block(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = f"```json\n{_valid_response()}\n```"
        result = analyze_article(_make_scraped(), mock_llm)
        assert result.title_cn == "阿森纳胜利"

    def test_raises_on_malformed_response(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "not json at all"
        with pytest.raises(ValueError, match="Failed to parse"):
            analyze_article(_make_scraped(), mock_llm)
