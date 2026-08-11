import json
import logging
import os

logger = logging.getLogger(__name__)


def get_config() -> dict:
    cookie_raw = os.environ.get("ATHLETIC_COOKIES", "[]")
    try:
        cookies = json.loads(cookie_raw)
    except json.JSONDecodeError:
        logger.error("ATHLETIC_COOKIES is not valid JSON, using empty list")
        cookies = []

    return {
        "athletic_cookies": cookies,
        "llm_base_url": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        "llm_api_key": os.environ.get("LLM_API_KEY", ""),
        "llm_model": os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
        "tts_voice": os.environ.get("TTS_VOICE", "zh-CN-YunjianNeural"),
        "tts_rate": os.environ.get("TTS_RATE", "+25%"),
    }
