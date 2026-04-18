import pytest
from unittest.mock import patch
from src.config import get_config


class TestGetConfig:
    def test_required_vars(self):
        env = {
            "ATHLETIC_COOKIES": '[{"name":"sid","value":"abc","domain":".nytimes.com","path":"/"}]',
            "LLM_API_KEY": "sk-test",
        }
        with patch.dict("os.environ", env, clear=True):
            config = get_config()
        assert config["llm_api_key"] == "sk-test"
        assert isinstance(config["athletic_cookies"], list)
        assert len(config["athletic_cookies"]) == 1

    def test_defaults(self):
        env = {"ATHLETIC_COOKIES": "[]", "LLM_API_KEY": "sk-test"}
        with patch.dict("os.environ", env, clear=True):
            config = get_config()
        assert config["llm_model"] == "deepseek-chat"
        assert config["tts_voice"] == "zh-CN-XiaoxiaoNeural"

    def test_invalid_cookies_json_defaults_to_empty_list(self):
        env = {"ATHLETIC_COOKIES": "not-json", "LLM_API_KEY": "sk-test"}
        with patch.dict("os.environ", env, clear=True):
            config = get_config()
        assert config["athletic_cookies"] == []
