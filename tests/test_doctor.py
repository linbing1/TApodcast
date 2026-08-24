from unittest.mock import AsyncMock

import pytest

import src.doctor as doctor
from src.doctor import CheckResult, DoctorReport
from src.models import PageContent


def test_cookie_configuration_validation(monkeypatch):
    monkeypatch.delenv("ATHLETIC_COOKIES", raising=False)
    assert doctor.check_cookie_config().status == "fail"

    monkeypatch.setenv(
        "ATHLETIC_COOKIES",
        '[{"name":"session","value":"secret","domain":".nytimes.com"}]',
    )
    result = doctor.check_cookie_config()

    assert result.status == "pass"
    assert "1 cookie" in result.detail


def test_llm_and_tts_configuration_validation(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert doctor.check_llm_config().status == "fail"

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    assert doctor.check_llm_config().status == "pass"

    monkeypatch.setenv("TTS_RATE", "fast")
    assert doctor.check_tts_config().status == "fail"
    monkeypatch.setenv("TTS_RATE", "+10%")
    assert doctor.check_tts_config().status == "pass"


def test_output_directory_check_uses_existing_parent(tmp_path):
    result = doctor.check_output_directory(str(tmp_path / "future" / "article"))

    assert result.status in ("pass", "warn")
    assert "writable parent" in result.detail


@pytest.mark.asyncio
async def test_article_access_detects_authenticated_content(monkeypatch):
    monkeypatch.setenv(
        "ATHLETIC_COOKIES",
        '[{"name":"session","value":"secret"}]',
    )
    mock_extract = AsyncMock(
        return_value=PageContent(
            url="https://example.com/article",
            title="Article title",
            main_text="x" * 500,
        )
    )
    monkeypatch.setattr(doctor, "extract_page_content", mock_extract)

    result = await doctor.check_article_access("https://example.com/article")

    assert result.status == "pass"
    assert "500 characters" in result.detail


@pytest.mark.asyncio
async def test_run_doctor_checks_includes_optional_online_checks(monkeypatch, tmp_path):
    passing = lambda name: CheckResult(name, "pass", "ok")
    monkeypatch.setattr(doctor, "check_python", lambda: passing("Python"))
    monkeypatch.setattr(doctor, "check_cookie_config", lambda: passing("Cookies"))
    monkeypatch.setattr(doctor, "check_llm_config", lambda: passing("LLM config"))
    monkeypatch.setattr(doctor, "check_tts_config", lambda: passing("TTS config"))
    monkeypatch.setattr(
        doctor,
        "check_output_directory",
        lambda output_dir: passing("Output"),
    )
    monkeypatch.setattr(
        doctor,
        "check_playwright",
        AsyncMock(return_value=passing("Playwright")),
    )
    monkeypatch.setattr(doctor, "check_ffmpeg", lambda: passing("FFmpeg"))
    monkeypatch.setattr(doctor, "check_font", lambda: passing("Font"))
    monkeypatch.setattr(
        doctor,
        "check_llm_online",
        AsyncMock(return_value=passing("LLM online")),
    )
    monkeypatch.setattr(
        doctor,
        "check_tts_online",
        AsyncMock(return_value=passing("TTS online")),
    )
    monkeypatch.setattr(
        doctor,
        "check_article_access",
        AsyncMock(return_value=passing("Article")),
    )

    report = await doctor.run_doctor_checks(
        output_dir=str(tmp_path),
        online=True,
        article_url="https://example.com/article",
    )

    assert report.passed
    assert len(report.checks) == 11
    doctor.check_llm_online.assert_awaited_once_with(tmp_path / "llm-usage.jsonl")
    doctor.check_tts_online.assert_awaited_once()
    doctor.check_article_access.assert_awaited_once_with(
        "https://example.com/article"
    )


def test_format_doctor_report_summarizes_statuses():
    report = DoctorReport([
        CheckResult("One", "pass", "ok"),
        CheckResult("Two", "warn", "check this"),
        CheckResult("Three", "fail", "broken"),
    ])

    text = doctor.format_doctor_report(report)

    assert "[PASS] One: ok" in text
    assert "[WARN] Two: check this" in text
    assert "[FAIL] Three: broken" in text
    assert "Summary: 1 passed, 1 warnings, 1 failed" in text
    assert not report.passed
