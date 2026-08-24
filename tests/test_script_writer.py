from unittest.mock import MagicMock

import pytest

from src.models import AnalyzedArticle, PodcastScript
from src.script_writer import (
    MAX_SCRIPT_CHARS,
    MIN_SCRIPT_CHARS,
    calculate_target_script_chars,
    count_source_chars,
    write_script,
)


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
        assert "事实清单" not in user_arg

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

    def test_includes_target_length_without_repeating_source_text(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _in_range_script()

        write_script(_make_analyzed(), mock_llm, target_chars=770)

        _, user_arg = mock_llm.complete.call_args.args
        assert "目标播报稿总长度约为 770 字" in user_arg
        assert "不需要后续再次调用模型压缩或扩充" in user_arg

    def test_rejects_response_missing_fixed_closing(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "欢迎收听英超每日观察，今天是今天。阿森纳主场取胜。"

        with pytest.raises(ValueError, match="missing required closing"):
            write_script(_make_analyzed(), mock_llm)

    def test_rejects_markdown_fence_in_response(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = (
            "欢迎收听英超每日观察，今天是今天。```阿森纳主场取胜。"
            "感谢收听，更多内容请关注英超每日观察。"
        )

        with pytest.raises(ValueError, match="Markdown code fence"):
            write_script(_make_analyzed(), mock_llm)


def test_count_source_chars_removes_whitespace():
    assert count_source_chars("阿森纳\n 主场\t击败 曼城") == 9


def test_calculate_target_script_chars_uses_linear_formula():
    assert calculate_target_script_chars(3_000) == 520
    assert calculate_target_script_chars(8_000) == 720
    assert calculate_target_script_chars(10_000) == 800


def test_calculate_target_script_chars_applies_bounds():
    assert calculate_target_script_chars(0) == MIN_SCRIPT_CHARS
    assert calculate_target_script_chars(100_000) == MAX_SCRIPT_CHARS


def test_calculate_target_script_chars_rejects_negative_source_length():
    try:
        calculate_target_script_chars(-1)
    except ValueError as exc:
        assert str(exc) == "source_chars must be non-negative"
    else:
        raise AssertionError("negative source length should fail")
