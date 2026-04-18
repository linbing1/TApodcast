# TApodcast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**GitHub:** `git@github.com:linbing1/TApodcast.git`

**Goal:** Build a CLI tool that takes a The Athletic article URL and produces a vertical MP4 video (Chinese audio + image slideshow + subtitles) ready for Douyin upload.

**Architecture:** Five sequential steps — scrape article text + images with Playwright, analyze with LLM into structured Chinese output, rewrite to oral podcast script with LLM, generate audio with edge-tts, assemble video with ffmpeg. Each step is an independent module with clear input/output types.

**Tech Stack:** Python 3.12, Playwright, httpx, edge-tts, ffmpeg (system), pytest + pytest-asyncio, unittest.mock

---

## File Map

| File | Responsibility |
|------|----------------|
| `main.py` | CLI entry point; chains all 5 steps |
| `src/models.py` | `ScrapedArticle`, `AnalyzedArticle`, `PodcastScript` dataclasses |
| `src/config.py` | Loads env vars into config dict |
| `src/llm.py` | LLM HTTP client with retry logic |
| `src/scraper.py` | Playwright: full text + image extraction + download |
| `src/analyzer.py` | LLM: English article → structured Chinese analysis |
| `src/script_writer.py` | LLM: analysis → oral podcast script |
| `src/tts_generator.py` | edge-tts: script → MP3 + SRT subtitles |
| `src/video_assembler.py` | ffmpeg: images + audio + subtitles → MP4 |
| `tests/conftest.py` | Shared pytest fixtures |
| `tests/test_models.py` | Model instantiation tests |
| `tests/test_config.py` | Config loading tests |
| `tests/test_scraper.py` | Scraper tests (Playwright + httpx mocked) |
| `tests/test_analyzer.py` | Analyzer tests (LLM mocked) |
| `tests/test_script_writer.py` | ScriptWriter tests (LLM mocked) |
| `tests/test_tts_generator.py` | TTS tests (edge-tts mocked) |
| `tests/test_video_assembler.py` | VideoAssembler tests (subprocess mocked) |
| `requirements.txt` | Python dependencies |
| `pytest.ini` | asyncio_mode = auto |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `requirements.txt`**

```
edge-tts>=6.1,<7
httpx>=0.27,<1
playwright>=1.49,<2
pytest>=8.0,<9
pytest-asyncio>=0.24,<1
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Create empty init files and conftest**

```bash
mkdir -p src tests
touch src/__init__.py tests/__init__.py tests/conftest.py
```

- [ ] **Step 4: Install dependencies**

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
```

Expected: all packages install without error.

- [ ] **Step 5: Verify pytest runs**

```bash
pytest tests/ -v
```

Expected: `no tests ran` (0 collected), exit 0.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pytest.ini src/__init__.py tests/__init__.py tests/conftest.py
git commit -m "feat: scaffold TApodcast project"
```

---

## Task 2: Data Models

**Files:**
- Create: `src/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

`tests/test_models.py`:
```python
from src.models import ScrapedArticle, AnalyzedArticle, PodcastScript


class TestScrapedArticle:
    def test_defaults(self):
        a = ScrapedArticle(title="Arsenal", link="https://example.com", full_text="text")
        assert a.image_paths == []

    def test_with_images(self):
        a = ScrapedArticle(
            title="Arsenal", link="https://example.com",
            full_text="text", image_paths=["/tmp/img1.jpg", "/tmp/img2.jpg"]
        )
        assert len(a.image_paths) == 2


class TestAnalyzedArticle:
    def test_instantiation(self):
        a = AnalyzedArticle(
            title_cn="标题", title_original="Title", article_type="新闻报道",
            importance=4, overview="概述", detail="详情",
            key_people_and_data="萨卡", impact="影响", link="https://example.com"
        )
        assert a.importance == 4


class TestPodcastScript:
    def test_instantiation(self):
        s = PodcastScript(text="今天的英超快报——阿森纳胜利。更多内容关注每日英超快报")
        assert "英超" in s.text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.models'`

- [ ] **Step 3: Create `src/models.py`**

```python
from dataclasses import dataclass, field


@dataclass
class ScrapedArticle:
    title: str
    link: str
    full_text: str
    image_paths: list[str] = field(default_factory=list)


@dataclass
class AnalyzedArticle:
    title_cn: str
    title_original: str
    article_type: str
    importance: int
    overview: str
    detail: str
    key_people_and_data: str
    impact: str
    link: str


@dataclass
class PodcastScript:
    text: str
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_models.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat: add data models"
```

---

## Task 3: Config and LLM Client

**Files:**
- Create: `src/config.py`
- Create: `src/llm.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing config test**

`tests/test_config.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Step 3: Create `src/config.py`**

```python
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
        "llm_base_url": os.environ.get(
            "LLM_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4"
        ),
        "llm_api_key": os.environ.get("LLM_API_KEY", ""),
        "llm_model": os.environ.get("LLM_MODEL", "deepseek-chat"),
        "tts_voice": os.environ.get("TTS_VOICE", "zh-CN-XiaoxiaoNeural"),
    }
```

- [ ] **Step 4: Run config tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Create `src/llm.py`** (identical logic to TAnews)

```python
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
```

- [ ] **Step 6: Commit**

```bash
git add src/config.py src/llm.py tests/test_config.py
git commit -m "feat: add config and LLM client"
```

---

## Task 4: Scraper

**Files:**
- Create: `src/scraper.py`
- Create: `tests/test_scraper.py`

The scraper navigates to an article URL, extracts the full text, finds all images with `naturalWidth >= 300`, downloads them, and raises `ValueError` if no images are found.

- [ ] **Step 1: Write failing tests**

`tests/test_scraper.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
import os

from src.scraper import scrape_article


class TestScrapeArticle:
    @pytest.mark.asyncio
    @patch("src.scraper.httpx.AsyncClient")
    @patch("src.scraper._extract_page_data", new_callable=AsyncMock)
    @patch("src.scraper.async_playwright")
    async def test_returns_scraped_article(self, mock_pw, mock_extract, mock_httpx_cls, tmp_path):
        _setup_playwright_mock(mock_pw)
        mock_extract.return_value = (
            "Arsenal vs City match report",
            "Arsenal Win",
            ["https://cdn.example.com/img1.jpg", "https://cdn.example.com/img2.jpg"],
        )
        mock_client = AsyncMock()
        mock_httpx_cls.return_value.__aenter__.return_value = mock_client
        mock_response = AsyncMock()
        mock_response.content = b"fake-image-data"
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        article = await scrape_article(
            "https://example.com/article", cookies=[], output_dir=str(tmp_path)
        )

        assert article.full_text == "Arsenal vs City match report"
        assert article.title == "Arsenal Win"
        assert len(article.image_paths) == 2
        assert all(os.path.exists(p) for p in article.image_paths)

    @pytest.mark.asyncio
    @patch("src.scraper._extract_page_data", new_callable=AsyncMock)
    @patch("src.scraper.async_playwright")
    async def test_raises_if_no_images(self, mock_pw, mock_extract, tmp_path):
        _setup_playwright_mock(mock_pw)
        mock_extract.return_value = ("Some text", "Title", [])

        with pytest.raises(ValueError, match="No images found"):
            await scrape_article(
                "https://example.com/article", cookies=[], output_dir=str(tmp_path)
            )

    @pytest.mark.asyncio
    @patch("src.scraper.httpx.AsyncClient")
    @patch("src.scraper._extract_page_data", new_callable=AsyncMock)
    @patch("src.scraper.async_playwright")
    async def test_skips_failed_image_downloads(self, mock_pw, mock_extract, mock_httpx_cls, tmp_path):
        _setup_playwright_mock(mock_pw)
        mock_extract.return_value = (
            "text", "Title",
            ["https://cdn.example.com/img1.jpg", "https://cdn.example.com/img2.jpg"],
        )
        mock_client = AsyncMock()
        mock_httpx_cls.return_value.__aenter__.return_value = mock_client
        # first succeeds, second raises
        ok_resp = AsyncMock()
        ok_resp.content = b"data"
        ok_resp.raise_for_status = MagicMock()
        mock_client.get.side_effect = [ok_resp, Exception("network error")]

        article = await scrape_article(
            "https://example.com/article", cookies=[], output_dir=str(tmp_path)
        )
        assert len(article.image_paths) == 1


def _setup_playwright_mock(mock_pw):
    mock_instance = AsyncMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_pw.return_value.__aenter__.return_value = mock_instance
    mock_instance.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scraper.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.scraper'`

- [ ] **Step 3: Create `src/scraper.py`**

```python
import logging
import os

import httpx
from playwright.async_api import Page, async_playwright

from src.models import ScrapedArticle

logger = logging.getLogger(__name__)

_ARTICLE_SELECTORS = [
    ".article-container",
    "[class*='ArticleWrapper']",
    "main article",
    "main",
]


def _convert_cookies(raw_cookies: list[dict]) -> list[dict]:
    converted = []
    for c in raw_cookies:
        same_site = c.get("sameSite", "Lax")
        if same_site in ("unspecified", "no_restriction"):
            same_site = "None"
        elif same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ""),
            "path": c.get("path", "/"),
            "sameSite": same_site,
        }
        if "expirationDate" in c:
            cookie["expires"] = c["expirationDate"]
        converted.append(cookie)
    return converted


async def _extract_page_data(page: Page, url: str) -> tuple[str, str, list[str]]:
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

    title = await page.title()

    text = ""
    for selector in _ARTICLE_SELECTORS:
        try:
            await page.wait_for_selector(selector, timeout=10000)
        except Exception:
            continue
        element = await page.query_selector(selector)
        if element:
            text = await element.inner_text()
            if len(text) > 100:
                break

    image_urls: list[str] = await page.evaluate(
        """() => Array.from(document.querySelectorAll('img'))
            .filter(img => img.naturalWidth >= 300 && img.naturalHeight >= 300)
            .map(img => img.src)
            .filter(src => src && src.startsWith('http'))"""
    )

    return text.strip(), title, image_urls


async def scrape_article(url: str, cookies: list[dict], output_dir: str) -> ScrapedArticle:
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    pw_cookies = _convert_cookies(cookies) if cookies else []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        if pw_cookies:
            await context.add_cookies(pw_cookies)
        page = await context.new_page()
        try:
            full_text, title, image_urls = await _extract_page_data(page, url)
        finally:
            await page.close()
            await browser.close()

    if not image_urls:
        raise ValueError(f"No images found in article: {url}")

    image_paths: list[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for i, img_url in enumerate(image_urls):
            try:
                resp = await client.get(img_url)
                resp.raise_for_status()
                ext = img_url.split(".")[-1].split("?")[0].lower()
                if ext not in ("jpg", "jpeg", "png", "webp"):
                    ext = "jpg"
                path = os.path.join(images_dir, f"{i:03d}.{ext}")
                with open(path, "wb") as f:
                    f.write(resp.content)
                image_paths.append(path)
                logger.info("Downloaded image %d: %s", i, img_url[:80])
            except Exception:
                logger.warning("Failed to download image %s", img_url)

    if not image_paths:
        raise ValueError(f"Failed to download any images for: {url}")

    return ScrapedArticle(title=title, link=url, full_text=full_text, image_paths=image_paths)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_scraper.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scraper.py tests/test_scraper.py
git commit -m "feat: add article scraper with image extraction"
```

---

## Task 5: Analyzer

**Files:**
- Create: `src/analyzer.py`
- Create: `tests/test_analyzer.py`

Adapted from TAnews: same LLM prompt and JSON parsing, but takes a single `ScrapedArticle` and returns a single `AnalyzedArticle` (raises on failure instead of skipping).

- [ ] **Step 1: Write failing tests**

`tests/test_analyzer.py`:
```python
import json
from unittest.mock import MagicMock

import pytest

from src.analyzer import analyze_article
from src.models import AnalyzedArticle, ScrapedArticle


def _make_scraped(title="Arsenal Win", full_text="Match report content") -> ScrapedArticle:
    return ScrapedArticle(title=title, link="https://example.com/1", full_text=full_text)


def _valid_response() -> str:
    return json.dumps({
        "title_cn": "阿森纳胜利",
        "title_original": "Arsenal Win",
        "article_type": "赛后分析",
        "importance": 4,
        "overview": "阿森纳在主场击败曼城。",
        "detail": "详细的比赛分析...",
        "key_people_and_data": "萨卡：2球",
        "impact": "阿森纳升至榜首",
        "link": "https://example.com/1",
    })


class TestAnalyzeArticle:
    def test_returns_analyzed_article(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _valid_response()
        result = analyze_article(_make_scraped(), mock_llm)
        assert isinstance(result, AnalyzedArticle)
        assert result.title_cn == "阿森纳胜利"
        assert result.importance == 4

    def test_passes_title_and_text_to_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _valid_response()
        article = _make_scraped(title="City Lose", full_text="City lost badly")
        analyze_article(article, mock_llm)
        _, user_arg = mock_llm.complete.call_args[0]
        assert "City Lose" in user_arg
        assert "City lost badly" in user_arg

    def test_handles_json_wrapped_in_code_block(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = f"```json\n{_valid_response()}\n```"
        result = analyze_article(_make_scraped(), mock_llm)
        assert result.title_cn == "阿森纳胜利"

    def test_raises_on_malformed_response(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "not json at all"
        with pytest.raises(ValueError, match="Failed to parse"):
            analyze_article(_make_scraped(), mock_llm)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_analyzer.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.analyzer'`

- [ ] **Step 3: Create `src/analyzer.py`**

```python
import json
import logging
from dataclasses import fields

from src.llm import LLMClient
from src.models import AnalyzedArticle, ScrapedArticle

logger = logging.getLogger(__name__)

_ANALYZED_FIELDS = {f.name for f in fields(AnalyzedArticle)}

_SYSTEM_PROMPT = """你是一位资深英超足球记者和分析师。请对以下英超文章进行深度中文分析。

核心原则：尽量保留原文的丰富内容，不要过度精简。读者希望通过你的分析获取接近原文的信息量，而不仅仅是摘要。

返回一个 JSON 对象，包含：
- title_cn: 中文标题翻译
- title_original: 英文原标题
- article_type: 文章类型（深度分析/新闻报道/战术解读/转会动态/赛后分析）
- importance: 重要性 1-5
- overview: 3-5 句话概述核心论点，包含关键结论和背景（中文）
- detail: 深度转述原文内容，要求：（1）保留原文中所有重要论据、数据、直接引语、战术细节和具体事例；（2）按原文逻辑结构组织，不要遗漏关键段落；（3）深度分析类 800-1200 字，普通新闻 400-600 字（中文）
- key_people_and_data: 涉及的关键人物和数据，列出所有被提及的人名、具体数据和统计（中文）
- impact: 影响分析与展望，包含短期和中长期影响（中文）
- link: 原文链接

仅返回 JSON 对象，不要添加任何其他文字。"""


def _parse_response(response: str) -> dict:
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {response[:200]}") from e
    if isinstance(data, list):
        data = data[0] if data else {}
    return data


def analyze_article(article: ScrapedArticle, llm: LLMClient) -> AnalyzedArticle:
    user_text = f"Title: {article.title}\nLink: {article.link}\nContent:\n{article.full_text}"
    response = llm.complete(_SYSTEM_PROMPT, user_text)
    data = _parse_response(response)
    filtered = {k: v for k, v in data.items() if k in _ANALYZED_FIELDS}
    return AnalyzedArticle(**filtered)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_analyzer.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/analyzer.py tests/test_analyzer.py
git commit -m "feat: add LLM article analyzer"
```

---

## Task 6: Script Writer

**Files:**
- Create: `src/script_writer.py`
- Create: `tests/test_script_writer.py`

- [ ] **Step 1: Write failing tests**

`tests/test_script_writer.py`:
```python
from unittest.mock import MagicMock

from src.models import AnalyzedArticle, PodcastScript
from src.script_writer import write_script


def _make_analyzed() -> AnalyzedArticle:
    return AnalyzedArticle(
        title_cn="阿森纳胜利",
        title_original="Arsenal Win",
        article_type="赛后分析",
        importance=4,
        overview="阿森纳在主场击败曼城。",
        detail="详细的比赛分析内容...",
        key_people_and_data="萨卡：2球",
        impact="阿森纳升至榜首",
        link="https://example.com/1",
    )


class TestWriteScript:
    def test_returns_podcast_script(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "今天的英超快报——阿森纳主场击败曼城。更多内容关注每日英超快报"
        result = write_script(_make_analyzed(), mock_llm)
        assert isinstance(result, PodcastScript)
        assert result.text == "今天的英超快报——阿森纳主场击败曼城。更多内容关注每日英超快报"

    def test_passes_all_fields_to_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "今天的英超快报——内容。更多内容关注每日英超快报"
        write_script(_make_analyzed(), mock_llm)
        _, user_arg = mock_llm.complete.call_args[0]
        assert "阿森纳胜利" in user_arg
        assert "阿森纳在主场击败曼城" in user_arg
        assert "萨卡：2球" in user_arg
        assert "阿森纳升至榜首" in user_arg

    def test_strips_whitespace_from_response(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "  今天的英超快报——内容。  \n"
        result = write_script(_make_analyzed(), mock_llm)
        assert result.text == "今天的英超快报——内容。"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_script_writer.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.script_writer'`

- [ ] **Step 3: Create `src/script_writer.py`**

```python
import logging

from src.llm import LLMClient
from src.models import AnalyzedArticle, PodcastScript

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一位专业的短视频播客主播。请将以下英超新闻分析改写为自然流畅的中文口语播报脚本。

要求：
- 开头固定为："今天的英超快报——"
- 结尾固定为："更多内容关注每日英超快报"
- 正文约 200-250 汉字（不含固定开头结尾）
- 使用口语化表达，避免书面语和长难句
- 保留最重要的事实、数据和人名
- 语气自然，像在和球迷朋友聊球

仅返回播报脚本文本，不要添加任何其他内容。"""


def write_script(article: AnalyzedArticle, llm: LLMClient) -> PodcastScript:
    user_text = (
        f"标题：{article.title_cn}\n"
        f"概述：{article.overview}\n"
        f"详情：{article.detail}\n"
        f"关键人物与数据：{article.key_people_and_data}\n"
        f"影响分析：{article.impact}"
    )
    response = llm.complete(_SYSTEM_PROMPT, user_text)
    return PodcastScript(text=response.strip())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_script_writer.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/script_writer.py tests/test_script_writer.py
git commit -m "feat: add podcast script writer"
```

---

## Task 7: TTS Generator

**Files:**
- Create: `src/tts_generator.py`
- Create: `tests/test_tts_generator.py`

Uses `edge-tts` to generate MP3 audio and SRT subtitles from the podcast script.

- [ ] **Step 1: Write failing tests**

`tests/test_tts_generator.py`:
```python
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models import PodcastScript
from src.tts_generator import generate_tts


class TestGenerateTTS:
    @pytest.mark.asyncio
    @patch("src.tts_generator.edge_tts.SubMaker")
    @patch("src.tts_generator.edge_tts.Communicate")
    async def test_writes_mp3_and_srt(self, mock_communicate_cls, mock_submaker_cls, tmp_path):
        mock_communicate = MagicMock()
        mock_communicate_cls.return_value = mock_communicate
        mock_communicate.stream.return_value = _fake_stream([
            {"type": "audio", "data": b"fake-audio-data"},
            {"type": "WordBoundary", "offset": 0, "duration": 1000, "text": "今天"},
        ])

        mock_submaker = MagicMock()
        mock_submaker_cls.return_value = mock_submaker
        mock_submaker.get_srt.return_value = "1\n00:00:00,000 --> 00:00:01,000\n今天\n\n"

        script = PodcastScript(text="今天的英超快报——内容。更多内容关注每日英超快报")
        mp3_path, srt_path = await generate_tts(script, "zh-CN-XiaoxiaoNeural", str(tmp_path))

        assert os.path.exists(mp3_path)
        assert os.path.exists(srt_path)
        assert open(mp3_path, "rb").read() == b"fake-audio-data"
        assert "今天" in open(srt_path).read()

    @pytest.mark.asyncio
    @patch("src.tts_generator.edge_tts.SubMaker")
    @patch("src.tts_generator.edge_tts.Communicate")
    async def test_uses_specified_voice(self, mock_communicate_cls, mock_submaker_cls, tmp_path):
        mock_communicate = MagicMock()
        mock_communicate_cls.return_value = mock_communicate
        mock_communicate.stream.return_value = _fake_stream([])
        mock_submaker_cls.return_value.get_srt.return_value = ""

        script = PodcastScript(text="内容")
        await generate_tts(script, "zh-CN-YunxiNeural", str(tmp_path))

        mock_communicate_cls.assert_called_once_with("内容", "zh-CN-YunxiNeural")


async def _fake_stream(chunks):
    for chunk in chunks:
        yield chunk
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tts_generator.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.tts_generator'`

- [ ] **Step 3: Create `src/tts_generator.py`**

```python
import logging
import os

import edge_tts

from src.models import PodcastScript

logger = logging.getLogger(__name__)


async def generate_tts(script: PodcastScript, voice: str, output_dir: str) -> tuple[str, str]:
    mp3_path = os.path.join(output_dir, "audio.mp3")
    srt_path = os.path.join(output_dir, "audio.srt")

    communicate = edge_tts.Communicate(script.text, voice)
    submaker = edge_tts.SubMaker()

    with open(mp3_path, "wb") as mp3_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)

    with open(srt_path, "w", encoding="utf-8") as srt_file:
        srt_file.write(submaker.get_srt())

    logger.info("Generated audio: %s, subtitles: %s", mp3_path, srt_path)
    return mp3_path, srt_path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tts_generator.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Verify edge-tts SubMaker API**

Run a quick smoke test to confirm `SubMaker.feed()` and `SubMaker.get_srt()` exist:

```bash
python -c "import edge_tts; s = edge_tts.SubMaker(); print(hasattr(s, 'feed'), hasattr(s, 'get_srt'))"
```

Expected: `True True`

If you see `False` for either, check the installed edge-tts version with `pip show edge-tts`. For older versions (< 6.1), the API is `s.create_sub((offset, duration), text)` and `s.generate_subs(words_in_cue=10)` — update `tts_generator.py` accordingly.

- [ ] **Step 6: Commit**

```bash
git add src/tts_generator.py tests/test_tts_generator.py
git commit -m "feat: add edge-tts audio and subtitle generator"
```

---

## Task 8: Video Assembler

**Files:**
- Create: `src/video_assembler.py`
- Create: `tests/test_video_assembler.py`

Uses ffmpeg to combine image slideshow + MP3 audio + SRT subtitles into a 1080×1920 MP4.

- [ ] **Step 1: Write failing tests**

`tests/test_video_assembler.py`:
```python
import os
import pytest
from unittest.mock import patch, MagicMock

from src.video_assembler import assemble_video, get_audio_duration


class TestGetAudioDuration:
    @patch("src.video_assembler.subprocess.run")
    def test_returns_duration_float(self, mock_run):
        mock_run.return_value = MagicMock(stdout="73.45\n")
        duration = get_audio_duration("/tmp/audio.mp3")
        assert duration == pytest.approx(73.45)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "ffprobe" in cmd
        assert "/tmp/audio.mp3" in cmd


class TestAssembleVideo:
    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration")
    def test_calls_ffmpeg_with_correct_args(self, mock_duration, mock_run, tmp_path):
        mock_duration.return_value = 60.0
        # Create fake image files
        images = []
        for i in range(3):
            p = str(tmp_path / f"img{i}.jpg")
            open(p, "wb").write(b"x")
            images.append(p)
        mp3 = str(tmp_path / "audio.mp3")
        srt = str(tmp_path / "audio.srt")
        output = str(tmp_path / "video.mp4")
        open(mp3, "wb").write(b"x")
        open(srt, "w").write("")

        mock_run.return_value = MagicMock(returncode=0)
        result = assemble_video(images, mp3, srt, output)

        assert result == output
        ffmpeg_call = mock_run.call_args_list[-1]
        cmd = ffmpeg_call[0][0]
        assert "ffmpeg" in cmd
        assert output in cmd

    @patch("src.video_assembler.subprocess.run")
    @patch("src.video_assembler.get_audio_duration")
    def test_creates_concat_file(self, mock_duration, mock_run, tmp_path):
        mock_duration.return_value = 30.0
        images = []
        for i in range(2):
            p = str(tmp_path / f"img{i}.jpg")
            open(p, "wb").write(b"x")
            images.append(p)

        mock_run.return_value = MagicMock(returncode=0)
        assemble_video(
            images,
            str(tmp_path / "audio.mp3"),
            str(tmp_path / "audio.srt"),
            str(tmp_path / "video.mp4"),
        )

        concat_path = str(tmp_path / "concat.txt")
        assert os.path.exists(concat_path)
        content = open(concat_path).read()
        assert "duration 15.000" in content  # 30s / 2 images
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_video_assembler.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.video_assembler'`

- [ ] **Step 3: Create `src/video_assembler.py`**

```python
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def get_audio_duration(mp3_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            mp3_path,
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def assemble_video(
    image_paths: list[str],
    mp3_path: str,
    srt_path: str,
    output_path: str,
) -> str:
    duration = get_audio_duration(mp3_path)
    n = len(image_paths)
    per_image = duration / n

    concat_path = os.path.join(os.path.dirname(output_path), "concat.txt")
    with open(concat_path, "w") as f:
        for path in image_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")
            f.write(f"duration {per_image:.3f}\n")
        f.write(f"file '{os.path.abspath(image_paths[-1])}'\n")

    # Scale image to fill 1080x1920 (crop center), burn subtitles
    abs_srt = os.path.abspath(srt_path)
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"subtitles='{abs_srt}':force_style="
        "'FontSize=22,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2,Alignment=2'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_path,
        "-i", mp3_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]

    logger.info("Running ffmpeg to assemble video...")
    subprocess.run(cmd, check=True, capture_output=True)
    logger.info("Video saved to %s", output_path)
    return output_path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_video_assembler.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Verify ffmpeg is available**

```bash
ffmpeg -version 2>&1 | head -1
ffprobe -version 2>&1 | head -1
```

Expected: version lines printed. If missing: `brew install ffmpeg`

- [ ] **Step 6: Commit**

```bash
git add src/video_assembler.py tests/test_video_assembler.py
git commit -m "feat: add ffmpeg video assembler"
```

---

## Task 9: CLI Entry Point

**Files:**
- Create: `main.py`

- [ ] **Step 1: Create `main.py`**

```python
import argparse
import asyncio
import logging
import os
from datetime import date

from src.analyzer import analyze_article
from src.config import get_config
from src.llm import LLMClient
from src.script_writer import write_script
from src.scraper import scrape_article
from src.tts_generator import generate_tts
from src.video_assembler import assemble_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _article_slug(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/") if p]
    slug = parts[-1] if parts else "article"
    return slug[:60]


async def run(url: str) -> None:
    config = get_config()
    slug = _article_slug(url)
    output_dir = os.path.join("output", str(date.today()), slug)
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Output directory: %s", output_dir)

    logger.info("Step 1: Scraping article and images...")
    article = await scrape_article(url, config["athletic_cookies"], output_dir)
    logger.info("Scraped %d chars text, %d images", len(article.full_text), len(article.image_paths))

    llm = LLMClient(config["llm_base_url"], config["llm_api_key"], config["llm_model"])

    logger.info("Step 2: Analyzing article (LLM)...")
    analyzed = analyze_article(article, llm)
    logger.info("Analysis complete: %s", analyzed.title_cn)

    logger.info("Step 3: Writing podcast script (LLM)...")
    script = write_script(analyzed, llm)
    logger.info("Script: %d chars", len(script.text))

    logger.info("Step 4: Generating audio with edge-tts...")
    mp3_path, srt_path = await generate_tts(script, config["tts_voice"], output_dir)

    logger.info("Step 5: Assembling video with ffmpeg...")
    video_path = os.path.join(output_dir, "video.mp4")
    assemble_video(article.image_paths, mp3_path, srt_path, video_path)

    logger.info("Done! Video: %s", video_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Douyin short video from a The Athletic article"
    )
    parser.add_argument("--url", required=True, help="The Athletic article URL")
    args = parser.parse_args()
    asyncio.run(run(args.url))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run full test suite to verify nothing is broken**

```bash
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Smoke test with a real article (requires env vars)**

```bash
export ATHLETIC_COOKIES='...'   # paste from TAnews .env
export LLM_API_KEY='...'
python main.py --url "https://www.nytimes.com/athletic/7202716/2026/04/17/mikel-arteta-arsenal-pressure-title-manchester-city/"
```

Expected: video appears at `output/{today}/mikel-arteta-arsenal-pressure-title-manchester-city/video.mp4`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add CLI entry point"
```

---

## Self-Review Notes

- **Spec coverage:** All 5 pipeline steps covered ✓. `ValueError` on no images ✓. Output directory structure ✓. Env vars table ✓. Cookie reuse ✓.
- **No placeholders:** All steps contain working code.
- **Type consistency:** `ScrapedArticle.image_paths: list[str]` used consistently in Task 4, 8, 9. `PodcastScript.text` used in Task 6, 7. `AnalyzedArticle` fields match between Task 2, 5, 6.
- **Edge case:** `get_srt()` API on edge-tts — verified in Task 7 Step 5 with an explicit smoke test.
