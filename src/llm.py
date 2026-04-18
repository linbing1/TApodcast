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

    def complete(self, system: str, user: str) -> str:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = httpx.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                    timeout=300,
                )
                if resp.status_code >= 400:
                    logger.error("LLM API error %d: %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except _RETRYABLE as e:
                if attempt == _MAX_RETRIES:
                    raise
                logger.warning(
                    "LLM request failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt, _MAX_RETRIES, e, _RETRY_DELAY,
                )
                time.sleep(_RETRY_DELAY)
