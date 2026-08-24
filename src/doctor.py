import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import edge_tts
import httpx
from playwright.async_api import async_playwright

from src.scraper import extract_page_content
from src.subtitle_renderer import find_cjk_font
from src.video_assembler import find_ffmpeg


def _record_online_llm_usage(
    usage_path: str | Path | None,
    *,
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error: str | None = None,
) -> None:
    if usage_path is None:
        return
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "doctor_request",
        "stage": "doctor-online",
        "prompt_version": "doctor-v1",
        "model": model,
        "cache_key": "",
        "attempts": 1,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    if error:
        record["error"] = error
    path = Path(usage_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as target:
        target.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(check.status != "fail" for check in self.checks)

    def count(self, status: str) -> int:
        return sum(check.status == status for check in self.checks)


def _result(name: str, status: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status=status, detail=detail)


def _load_cookies() -> tuple[list[dict], CheckResult]:
    raw = os.environ.get("ATHLETIC_COOKIES", "").strip()
    if not raw:
        return [], _result("Athletic cookies", "fail", "ATHLETIC_COOKIES is missing")
    try:
        cookies = json.loads(raw)
    except json.JSONDecodeError:
        return [], _result(
            "Athletic cookies",
            "fail",
            "ATHLETIC_COOKIES is not valid JSON",
        )
    if not isinstance(cookies, list) or not cookies:
        return [], _result(
            "Athletic cookies",
            "fail",
            "ATHLETIC_COOKIES must be a non-empty JSON array",
        )
    valid = [
        cookie
        for cookie in cookies
        if isinstance(cookie, dict)
        and cookie.get("name")
        and cookie.get("value") is not None
    ]
    if not valid:
        return [], _result(
            "Athletic cookies",
            "fail",
            "No cookie entry contains both name and value",
        )
    if len(valid) != len(cookies):
        return valid, _result(
            "Athletic cookies",
            "warn",
            f"Loaded {len(valid)} valid cookies; ignored {len(cookies) - len(valid)} malformed entries",
        )
    return valid, _result(
        "Athletic cookies",
        "pass",
        f"Loaded {len(valid)} cookie entries",
    )


def check_python() -> CheckResult:
    version = sys.version_info
    status = "pass" if version >= (3, 12) else "fail"
    return _result(
        "Python",
        status,
        f"{version.major}.{version.minor}.{version.micro}"
        + ("" if status == "pass" else "; Python 3.12 or newer is required"),
    )


def check_cookie_config() -> CheckResult:
    return _load_cookies()[1]


def check_llm_config() -> CheckResult:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").strip()
    model = os.environ.get("LLM_MODEL", "deepseek-v4-flash").strip()
    if not api_key:
        return _result("LLM configuration", "fail", "LLM_API_KEY is missing")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return _result("LLM configuration", "fail", f"Invalid LLM_BASE_URL: {base_url}")
    if not model:
        return _result("LLM configuration", "fail", "LLM_MODEL is empty")
    return _result(
        "LLM configuration",
        "pass",
        f"model={model}, endpoint={parsed.scheme}://{parsed.netloc}",
    )


def check_tts_config() -> CheckResult:
    voice = os.environ.get("TTS_VOICE", "zh-CN-YunjianNeural").strip()
    rate = os.environ.get("TTS_RATE", "+10%").strip()
    if not voice:
        return _result("TTS configuration", "fail", "TTS_VOICE is empty")
    if not re.fullmatch(r"[+-]\d+%", rate):
        return _result("TTS configuration", "fail", f"Invalid TTS_RATE: {rate}")
    return _result("TTS configuration", "pass", f"voice={voice}, rate={rate}")


def check_output_directory(output_dir: str) -> CheckResult:
    target = Path(output_dir).expanduser().resolve()
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.exists() or not probe.is_dir():
        return _result("Output directory", "fail", f"No existing parent for {target}")
    try:
        with tempfile.NamedTemporaryFile(dir=probe, prefix=".tapodcast-doctor-"):
            pass
    except OSError as error:
        return _result("Output directory", "fail", f"Not writable: {probe} ({error})")

    free_bytes = shutil.disk_usage(probe).free
    free_gb = free_bytes / (1024 ** 3)
    if free_bytes < 512 * 1024 * 1024:
        status = "fail"
        suffix = "; at least 512 MB free space is required"
    elif free_bytes < 2 * 1024 * 1024 * 1024:
        status = "warn"
        suffix = "; video frame rendering may run out of space"
    else:
        status = "pass"
        suffix = ""
    return _result(
        "Output directory",
        status,
        f"writable parent={probe}, free={free_gb:.1f} GB{suffix}",
    )


async def check_playwright() -> CheckResult:
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            version = browser.version
            await browser.close()
    except Exception as error:
        return _result("Playwright Chromium", "fail", str(error))
    return _result("Playwright Chromium", "pass", f"Chromium {version}")


def check_ffmpeg() -> CheckResult:
    try:
        ffmpeg_path = find_ffmpeg()
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as error:
        return _result("FFmpeg/libass", "fail", str(error))
    version_line = result.stdout.splitlines()[0] if result.stdout else ffmpeg_path
    return _result("FFmpeg/libass", "pass", version_line)


def check_font() -> CheckResult:
    font_path = find_cjk_font()
    if not font_path:
        return _result(
            "Chinese font",
            "fail",
            "No CJK font found; install Noto Sans CJK SC or set CJK_FONT_PATH",
        )
    return _result("Chinese font", "pass", font_path)


async def check_llm_online(usage_path: str | Path | None = None) -> CheckResult:
    config_result = check_llm_config()
    if config_result.status == "fail":
        return _result("LLM connectivity", "fail", config_result.detail)
    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    api_key = os.environ["LLM_API_KEY"].strip()
    model = os.environ.get("LLM_MODEL", "deepseek-v4-flash").strip()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 2,
                },
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("choices"):
                raise ValueError("response does not contain choices")
            usage = data.get("usage") or {}
            _record_online_llm_usage(
                usage_path,
                model=model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
    except Exception as error:
        _record_online_llm_usage(usage_path, model=model, error=str(error))
        return _result("LLM connectivity", "fail", str(error))
    return _result("LLM connectivity", "pass", f"Connected with model {model}")


async def check_tts_online() -> CheckResult:
    voice = os.environ.get("TTS_VOICE", "zh-CN-YunjianNeural").strip()
    try:
        voices = await edge_tts.list_voices()
    except Exception as error:
        return _result("TTS connectivity", "fail", str(error))
    available = {item.get("ShortName") for item in voices}
    if voice not in available:
        return _result(
            "TTS connectivity",
            "fail",
            f"Voice is not available: {voice}",
        )
    return _result("TTS connectivity", "pass", f"Voice is available: {voice}")


async def check_article_access(url: str) -> CheckResult:
    cookies, cookie_result = _load_cookies()
    if cookie_result.status == "fail":
        return _result("Athletic article access", "fail", cookie_result.detail)
    try:
        content = await extract_page_content(url, cookies)
    except Exception as error:
        return _result("Athletic article access", "fail", str(error))
    body_length = len(content.main_text.strip())
    if body_length < 300:
        return _result(
            "Athletic article access",
            "fail",
            f"Extracted only {body_length} characters; login may have expired",
        )
    return _result(
        "Athletic article access",
        "pass",
        f"Extracted {body_length} characters from {content.title}",
    )


async def run_doctor_checks(
    *,
    output_dir: str = "output",
    online: bool = False,
    article_url: str = "",
) -> DoctorReport:
    checks = [
        check_python(),
        check_cookie_config(),
        check_llm_config(),
        check_tts_config(),
        check_output_directory(output_dir),
        await check_playwright(),
        check_ffmpeg(),
        check_font(),
    ]
    if online:
        usage_path = Path(output_dir) / "llm-usage.jsonl"
        checks.extend([await check_llm_online(usage_path), await check_tts_online()])
    if article_url:
        checks.append(await check_article_access(article_url))
    return DoctorReport(checks)


def format_doctor_report(report: DoctorReport) -> str:
    labels = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = [
        f"[{labels.get(check.status, check.status.upper())}] "
        f"{check.name}: {check.detail}"
        for check in report.checks
    ]
    lines.append(
        "Summary: "
        f"{report.count('pass')} passed, "
        f"{report.count('warn')} warnings, "
        f"{report.count('fail')} failed"
    )
    return "\n".join(lines)
