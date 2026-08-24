import json
from unittest.mock import patch

import httpx
import pytest

from src.llm import LLMBudgetExceededError, LLMClient


class TestLLMClient:
    def test_missing_api_key_raises(self):
        with pytest.raises(RuntimeError, match="LLM_API_KEY"):
            LLMClient("https://api.example.com/v1", "", "test-model")

    def test_valid_api_key_constructs(self):
        client = LLMClient("https://api.example.com/v1", "sk-test", "test-model")
        assert client.model == "test-model"

    @patch("src.llm.httpx.post")
    def test_successful_response_is_cached_and_usage_is_recorded(self, mock_post, tmp_path):
        mock_post.return_value = httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "cached response"}}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
        )
        usage_path = tmp_path / "llm-usage.jsonl"
        callback_events = []
        client = LLMClient(
            "https://api.example.com/v1",
            "sk-test",
            "test-model",
            cache_dir=tmp_path / ".llm-cache",
            usage_path=usage_path,
            max_requests=2,
            usage_callback=lambda: callback_events.append("updated"),
        )

        first = client.complete(
            "system",
            "user",
            stage="analyze-content",
            prompt_version="analyzer-v1",
        )
        second = client.complete(
            "system",
            "user",
            stage="analyze-content",
            prompt_version="analyzer-v1",
        )

        assert first == "cached response"
        assert second == first
        mock_post.assert_called_once()
        records = [
            json.loads(line)
            for line in usage_path.read_text(encoding="utf-8").splitlines()
        ]
        assert [record["event"] for record in records] == [
            "api_request",
            "cache_hit",
        ]
        assert records[0]["total_tokens"] == 18
        assert records[0]["stage"] == "analyze-content"
        assert callback_events == ["updated", "updated"]

    @patch("src.llm.httpx.post")
    def test_request_budget_blocks_uncached_calls(self, mock_post, tmp_path):
        mock_post.return_value = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "response"}}]},
        )
        usage_path = tmp_path / "llm-usage.jsonl"
        callback_events = []
        client = LLMClient(
            "https://api.example.com/v1",
            "sk-test",
            "test-model",
            usage_path=usage_path,
            max_requests=1,
            usage_callback=lambda: callback_events.append("updated"),
        )

        client.complete("system", "first", stage="analyze-content")

        with pytest.raises(LLMBudgetExceededError, match="1/1"):
            client.complete("system", "second", stage="write-script")

        assert mock_post.call_count == 1
        records = [
            json.loads(line)
            for line in usage_path.read_text(encoding="utf-8").splitlines()
        ]
        assert [record["event"] for record in records] == [
            "api_request",
            "budget_exceeded",
        ]
        assert records[-1]["stage"] == "write-script"
        assert callback_events == ["updated", "updated"]
