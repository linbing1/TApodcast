from unittest.mock import MagicMock

import pytest

from src.models import AnalyzedArticle, PodcastScript, SourceFact
from src.script_writer import fit_script_length, write_script


def _in_range_script() -> str:
    return (
        "欢迎收听英超每日观察，今天是今天。"
        + "阿森纳主场击败曼城。" * 82
        + "感谢收听，更多内容请关注英超每日观察。"
    )


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
        source_facts=[
            SourceFact(
                fact_id="F001",
                claim="阿森纳在主场击败曼城。",
                evidence="Arsenal beat Manchester City at home.",
                category="比赛",
                importance="critical",
            )
        ],
    )


class TestWriteScript:
    def test_returns_podcast_script(self):
        mock_llm = MagicMock()
        in_range = _in_range_script()
        mock_llm.complete.return_value = in_range
        result = write_script(_make_analyzed(), mock_llm)
        assert isinstance(result, PodcastScript)
        assert result.text == in_range
        assert mock_llm.complete.call_count == 1

    def test_passes_all_fields_to_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _in_range_script()
        write_script(_make_analyzed(), mock_llm)
        _, user_arg = mock_llm.complete.call_args_list[0].args
        assert "阿森纳胜利" in user_arg
        assert "阿森纳在主场击败曼城" in user_arg
        assert "萨卡：2球" in user_arg
        assert "阿森纳升至榜首" in user_arg
        assert "F001" in user_arg

    def test_strips_whitespace_from_response(self):
        mock_llm = MagicMock()
        in_range = _in_range_script()
        mock_llm.complete.return_value = f"  {in_range}  \n"
        result = write_script(_make_analyzed(), mock_llm)
        assert result.text == in_range

    def test_compresses_script_when_initial_response_is_too_long(self):
        mock_llm = MagicMock()
        long_script = "欢迎收听英超每日观察，今天是今天。" + ("重要内容。" * 200)
        compressed_script = _in_range_script()
        mock_llm.complete.side_effect = [long_script, compressed_script]

        result = write_script(_make_analyzed(), mock_llm)

        assert result.text == compressed_script
        assert mock_llm.complete.call_count == 2
        assert "压缩到不超过" in mock_llm.complete.call_args.args[1]

    def test_expands_script_when_initial_response_is_too_short(self):
        mock_llm = MagicMock()
        short_script = "欢迎收听英超每日观察，今天是今天。内容太短。感谢收听，更多内容请关注英超每日观察。"
        expanded_script = _in_range_script()
        mock_llm.complete.side_effect = [short_script, expanded_script]

        result = write_script(_make_analyzed(), mock_llm)

        assert result.text == expanded_script
        assert mock_llm.complete.call_count == 2
        expansion_prompt = mock_llm.complete.call_args.args[1]
        assert "扩充到" in expansion_prompt
        assert "阿森纳在主场击败曼城。" in expansion_prompt

    def test_retries_expansion_that_overshoots_limit(self):
        mock_llm = MagicMock()
        short_script = "欢迎收听英超每日观察，今天是今天。内容太短。感谢收听，更多内容请关注英超每日观察。"
        over_limit = _in_range_script() + "补充内容。" * 30
        in_range = _in_range_script()
        mock_llm.complete.side_effect = [short_script, over_limit, in_range]

        result = write_script(_make_analyzed(), mock_llm)

        assert result.text == in_range
        assert mock_llm.complete.call_count == 3

    def test_keeps_short_script_when_expansion_keeps_overshooting(self):
        mock_llm = MagicMock()
        short_script = "欢迎收听英超每日观察，今天是今天。内容太短。感谢收听，更多内容请关注英超每日观察。"
        over_limit = _in_range_script() + "补充内容。" * 30
        mock_llm.complete.side_effect = [short_script, over_limit, over_limit]

        result = write_script(_make_analyzed(), mock_llm)

        assert result.text == short_script
        assert mock_llm.complete.call_count == 3

    def test_compresses_then_expands_overshot_draft(self):
        mock_llm = MagicMock()
        long_script = "欢迎收听英超每日观察，今天是今天。" + ("重要内容。" * 200)
        compressed_short = "欢迎收听英超每日观察，今天是今天。核心内容。感谢收听，更多内容请关注英超每日观察。"
        in_range = _in_range_script()
        mock_llm.complete.side_effect = [long_script, compressed_short, in_range]

        result = write_script(_make_analyzed(), mock_llm)

        assert result.text == in_range
        assert mock_llm.complete.call_count == 3

    def test_raises_if_compression_still_exceeds_limit(self):
        mock_llm = MagicMock()
        long_script = "很长的稿子。" * 200
        mock_llm.complete.side_effect = [long_script, long_script, long_script]

        with pytest.raises(ValueError, match="too long"):
            write_script(_make_analyzed(), mock_llm)


class TestFitScriptLength:
    def test_leaves_short_text_unchanged_without_facts(self):
        mock_llm = MagicMock()
        short_text = "欢迎收听英超每日观察。很短的稿子。"

        assert fit_script_length(short_text, mock_llm) == short_text
        mock_llm.complete.assert_not_called()
