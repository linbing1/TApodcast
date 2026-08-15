import pytest
from src.llm import LLMClient


class TestLLMClient:
    def test_missing_api_key_raises(self):
        with pytest.raises(RuntimeError, match="LLM_API_KEY"):
            LLMClient("https://api.example.com/v1", "", "test-model")

    def test_valid_api_key_constructs(self):
        client = LLMClient("https://api.example.com/v1", "sk-test", "test-model")
        assert client.model == "test-model"
