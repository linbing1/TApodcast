import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.storage import atomic_write_json

logger = logging.getLogger(__name__)


_RETRYABLE = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout)
_MAX_RETRIES = 3
_RETRY_DELAY = 5


class LLMBudgetExceededError(RuntimeError):
    pass


@dataclass
class LLMClient:
    base_url: str
    api_key: str
    model: str
    cache_dir: str | Path | None = None
    usage_path: str | Path | None = None
    max_requests: int | None = None

    def __post_init__(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "缺少 LLM_API_KEY 环境变量。配置只从进程环境变量读取（不支持 .env 文件），"
                "请先 export LLM_API_KEY=... 再运行。"
                "注意脚本、定时任务等非交互 shell 不会自动加载 ~/.zshrc。"
            )
        if self.cache_dir is not None:
            self.cache_dir = Path(self.cache_dir)
        if self.usage_path is not None:
            self.usage_path = Path(self.usage_path)

    def complete(
        self,
        system: str,
        user: str,
        json_mode: bool = False,
        *,
        stage: str = "",
        prompt_version: str = "",
    ) -> str:
        cache_key = self._cache_key(
            system,
            user,
            json_mode=json_mode,
            stage=stage,
            prompt_version=prompt_version,
        )
        cached = self._read_cache(cache_key)
        if cached is not None:
            self._record_usage(
                event="cache_hit",
                stage=stage,
                prompt_version=prompt_version,
                cache_key=cache_key,
                attempts=0,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
            )
            return cached

        self._check_budget(stage)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(1, _MAX_RETRIES + 1):
            delay = _RETRY_DELAY * (2 ** (attempt - 1))
            try:
                resp = httpx.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=300,
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt == _MAX_RETRIES:
                        logger.error("LLM API error %d: %s", resp.status_code, resp.text[:500])
                        self._record_usage(
                            event="api_request",
                            stage=stage,
                            prompt_version=prompt_version,
                            cache_key=cache_key,
                            attempts=attempt,
                            prompt_tokens=None,
                            completion_tokens=None,
                            total_tokens=None,
                            error=f"HTTP {resp.status_code}",
                        )
                        resp.raise_for_status()
                    logger.warning(
                        "LLM API error %d (attempt %d/%d). Retrying in %ds...",
                        resp.status_code, attempt, _MAX_RETRIES, delay,
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code >= 400:
                    logger.error("LLM API error %d: %s", resp.status_code, resp.text[:500])
                    self._record_usage(
                        event="api_request",
                        stage=stage,
                        prompt_version=prompt_version,
                        cache_key=cache_key,
                        attempts=attempt,
                        prompt_tokens=None,
                        completion_tokens=None,
                        total_tokens=None,
                        error=f"HTTP {resp.status_code}",
                    )
                    resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                self._record_usage(
                    event="api_request",
                    stage=stage,
                    prompt_version=prompt_version,
                    cache_key=cache_key,
                    attempts=attempt,
                    prompt_tokens=self._token_value(usage, "prompt_tokens"),
                    completion_tokens=self._token_value(usage, "completion_tokens"),
                    total_tokens=self._token_value(usage, "total_tokens"),
                )
                self._write_cache(cache_key, content)
                return content
            except _RETRYABLE as error:
                if attempt == _MAX_RETRIES:
                    self._record_usage(
                        event="api_request",
                        stage=stage,
                        prompt_version=prompt_version,
                        cache_key=cache_key,
                        attempts=attempt,
                        prompt_tokens=None,
                        completion_tokens=None,
                        total_tokens=None,
                        error=str(error),
                    )
                    raise
                logger.warning(
                    "LLM request failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt,
                    _MAX_RETRIES,
                    error,
                    delay,
                )
                time.sleep(delay)
            except (KeyError, TypeError, ValueError) as error:
                self._record_usage(
                    event="api_request",
                    stage=stage,
                    prompt_version=prompt_version,
                    cache_key=cache_key,
                    attempts=attempt,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    error=str(error),
                )
                raise

        raise RuntimeError("LLM request loop exited unexpectedly")

    def _cache_key(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool,
        stage: str,
        prompt_version: str,
    ) -> str:
        payload = {
            "base_url": self.base_url.rstrip("/"),
            "model": self.model,
            "system": system,
            "user": user,
            "json_mode": json_mode,
            "stage": stage,
            "prompt_version": prompt_version,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _cache_path(self, cache_key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> str | None:
        path = self._cache_path(cache_key)
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Ignoring invalid LLM cache entry %s: %s", path, error)
            return None
        response = data.get("response") if isinstance(data, dict) else None
        return response if isinstance(response, str) and response else None

    def _write_cache(self, cache_key: str, response: str) -> None:
        path = self._cache_path(cache_key)
        if path is None:
            return
        atomic_write_json(
            path,
            {
                "cache_key": cache_key,
                "model": self.model,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "response": response,
            },
        )

    def _usage_records(self) -> list[dict[str, Any]]:
        if self.usage_path is None or not self.usage_path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            lines = self.usage_path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            logger.warning("Unable to read LLM usage log %s: %s", self.usage_path, error)
            return records
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def _check_budget(self, stage: str) -> None:
        if self.max_requests is None:
            return
        request_count = sum(
            record.get("event") == "api_request" for record in self._usage_records()
        )
        if request_count >= self.max_requests:
            raise LLMBudgetExceededError(
                f"LLM request budget exceeded before stage {stage or 'unknown'}: "
                f"{request_count}/{self.max_requests} requests"
            )

    def _record_usage(
        self,
        *,
        event: str,
        stage: str,
        prompt_version: str,
        cache_key: str,
        attempts: int,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        error: str | None = None,
    ) -> None:
        if self.usage_path is None:
            return
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "stage": stage,
            "prompt_version": prompt_version,
            "model": self.model,
            "cache_key": cache_key,
            "attempts": attempts,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        if error:
            record["error"] = error
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_path.open("a", encoding="utf-8") as target:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _token_value(usage: dict[str, Any], key: str) -> int | None:
        value = usage.get(key)
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        return None
