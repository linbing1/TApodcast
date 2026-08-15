import json
import os


def get_config() -> dict:
    cookie_raw = os.environ.get("ATHLETIC_COOKIES", "").strip()
    if not cookie_raw:
        raise RuntimeError(
            "缺少 ATHLETIC_COOKIES 环境变量。本项目只处理 The Athletic 文章，"
            "需要登录 Cookie 才能抓取完整正文。"
            "请用 Cookie-Editor 插件导出 JSON 数组后 export。"
            "注意脚本、定时任务等非交互 shell 不会自动加载 ~/.zshrc。"
        )
    try:
        cookies = json.loads(cookie_raw)
    except json.JSONDecodeError:
        raise RuntimeError(
            "ATHLETIC_COOKIES 不是合法的 JSON，请重新从浏览器插件导出 Cookie 数组。"
        )
    if not isinstance(cookies, list) or not cookies:
        raise RuntimeError("ATHLETIC_COOKIES 必须是非空的 Cookie JSON 数组。")

    return {
        "athletic_cookies": cookies,
        "llm_base_url": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        "llm_api_key": os.environ.get("LLM_API_KEY", ""),
        "llm_model": os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
        "tts_voice": os.environ.get("TTS_VOICE", "zh-CN-YunjianNeural"),
        "tts_rate": os.environ.get("TTS_RATE", "+10%"),
    }
