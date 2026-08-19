import pytest

from src.llm_json import loads, strip_code_fence


class TestStripCodeFence:
    def test_strips_json_fence(self):
        assert strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_keeps_plain_json(self):
        assert strip_code_fence('  {"a": 1}  ') == '{"a": 1}'

    def test_handles_fence_without_newline(self):
        assert strip_code_fence("```") == ""


class TestLoads:
    def test_parses_plain_object(self):
        assert loads('{"a": 1}') == {"a": 1}

    def test_parses_fenced_object(self):
        assert loads('```json\n{"a": 1}\n```') == {"a": 1}

    def test_tolerates_raw_control_characters_in_strings(self):
        raw = '{"detail": "第一行\n第二行\t缩进"}'
        with pytest.raises(ValueError):
            __import__("json").loads(raw)
        assert loads(raw) == {"detail": "第一行\n第二行\t缩进"}

    def test_raises_on_malformed_json(self):
        with pytest.raises(ValueError):
            loads("not json at all")
