from unittest.mock import MagicMock

import pytest

from src.models import AnalyzedArticle, PodcastScript
from src.script_writer import write_script


def _make_analyzed() -> AnalyzedArticle:
    return AnalyzedArticle(
        title_cn="阿森纳胜利",
        title_original="Arsenal Win",
        article_type="赛后分析",
        overview="阿森纳在主场击败曼城。",
        detail="详细的比赛分析内容...",
        key_people_and_data="萨卡：2球",
        impact="阿森纳升至榜首",
        link="https://example.com/1",
    )


class TestWriteScript:
    def test_returns_podcast_script(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "今天的英超快报——阿森纳主场击败曼城。更多内容关注每日英超快报"
        result = write_script(_make_analyzed(), mock_llm)
        assert isinstance(result, PodcastScript)
        assert result.text == "今天的英超快报——阿森纳主场击败曼城。更多内容关注每日英超快报"

    def test_passes_all_fields_to_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "今天的英超快报——内容。更多内容关注每日英超快报"
        write_script(_make_analyzed(), mock_llm)
        _, user_arg = mock_llm.complete.call_args[0]
        assert "阿森纳胜利" in user_arg
        assert "阿森纳在主场击败曼城" in user_arg
        assert "萨卡：2球" in user_arg
        assert "阿森纳升至榜首" in user_arg

    def test_strips_whitespace_from_response(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "  今天的英超快报——内容。  \n"
        result = write_script(_make_analyzed(), mock_llm)
        assert result.text == "今天的英超快报——内容。"

    def test_compresses_script_when_initial_response_is_too_long(self):
        mock_llm = MagicMock()
        long_script = "欢迎收听英超每日观察，今天是今天。" + ("重要内容。" * 200)
        compressed_script = "欢迎收听英超每日观察，今天是今天。核心内容。感谢收听，更多内容请关注英超每日观察。"
        mock_llm.complete.side_effect = [long_script, compressed_script]

        result = write_script(_make_analyzed(), mock_llm)

        assert result.text == compressed_script
        assert mock_llm.complete.call_count == 2
        assert "压缩到不超过" in mock_llm.complete.call_args.args[1]

    def test_raises_if_compression_still_exceeds_limit(self):
        mock_llm = MagicMock()
        long_script = "很长的稿子。" * 200
        mock_llm.complete.side_effect = [long_script, long_script, long_script]

        with pytest.raises(ValueError, match="too long"):
            write_script(_make_analyzed(), mock_llm)
