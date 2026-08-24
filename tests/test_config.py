import pytest
from unittest.mock import patch
from src.config import get_config

_VALID_COOKIES = '[{"name":"sid","value":"abc","domain":".nytimes.com","path":"/"}]'


class TestGetConfig:
    def test_required_vars(self):
        env = {
            "ATHLETIC_COOKIES": _VALID_COOKIES,
            "LLM_API_KEY": "sk-test",
        }
        with patch.dict("os.environ", env, clear=True):
            config = get_config()
        assert config["llm_api_key"] == "sk-test"
        assert isinstance(config["athletic_cookies"], list)
        assert len(config["athletic_cookies"]) == 1

    def test_defaults(self):
        env = {"ATHLETIC_COOKIES": _VALID_COOKIES, "LLM_API_KEY": "sk-test"}
        with patch.dict("os.environ", env, clear=True):
            config = get_config()
        assert config["llm_model"] == "deepseek-v4-flash"
        assert config["llm_max_requests"] == 12
        assert config["tts_voice"] == "zh-CN-YunjianNeural"
        assert config["tts_rate"] == "+10%"

    def test_missing_cookies_raises(self):
        env = {"LLM_API_KEY": "sk-test"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="ATHLETIC_COOKIES"):
                get_config()

    def test_invalid_cookies_json_raises(self):
        env = {"ATHLETIC_COOKIES": "not-json", "LLM_API_KEY": "sk-test"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="JSON"):
                get_config()

    def test_empty_cookies_list_raises(self):
        env = {"ATHLETIC_COOKIES": "[]", "LLM_API_KEY": "sk-test"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="非空"):
                get_config()
