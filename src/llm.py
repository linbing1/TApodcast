import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


_RETRYABLE = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout)
_MAX_RETRIES = 3
_RETRY_DELAY = 5


@dataclass
class LLMClient:
    base_url: str
    api_key: str
    model: str

    def __post_init__(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "缺少 LLM_API_KEY 环境变量。配置只从进程环境变量读取（不支持 .env 文件），"
                "请先 export LLM_API_KEY=... 再运行。"
                "注意脚本、定时任务等非交互 shell 不会自动加载 ~/.zshrc。"
            )

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        payload: dict = {
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
                        resp.raise_for_status()
                    logger.warning(
                        "LLM API error %d (attempt %d/%d). Retrying in %ds...",
                        resp.status_code, attempt, _MAX_RETRIES, delay,
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code >= 400:
                    logger.error("LLM API error %d: %s", resp.status_code, resp.text[:500])
                    resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except _RETRYABLE as e:
                if attempt == _MAX_RETRIES:
                    raise
                logger.warning(
                    "LLM request failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt, _MAX_RETRIES, e, delay,
                )
                time.sleep(delay)
