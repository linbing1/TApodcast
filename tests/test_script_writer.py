from unittest.mock import MagicMock

from src.models import AnalyzedArticle, PodcastScript, SourceFact
from src.script_writer import write_script


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

    def test_does_not_adjust_script_length(self):
        mock_llm = MagicMock()
        short_script = "欢迎收听英超每日观察，今天是今天。内容不长。感谢收听，更多内容请关注英超每日观察。"
        mock_llm.complete.return_value = f"  {short_script}  "

        result = write_script(_make_analyzed(), mock_llm)

        assert result.text == short_script
        assert mock_llm.complete.call_count == 1
