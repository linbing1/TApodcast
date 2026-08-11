import asyncio
import io
import logging
import os

import httpx
from PIL import Image as PILImage
from playwright.async_api import Page, async_playwright

from src.models import ScrapedArticle

_MIN_WIDTH = 600
_MIN_HEIGHT = 300

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
    await page.goto(url, wait_until="domcontentloaded", timeout=120000)

    title = await page.title()

    text = ""
    matched_selector = None
    for selector in _ARTICLE_SELECTORS:
        try:
            await page.wait_for_selector(selector, timeout=10000)
        except Exception:
            continue
        element = await page.query_selector(selector)
        if element:
            text = await element.inner_text()
            if len(text) > 100:
                matched_selector = selector
                break

    if not matched_selector:
        raise ValueError(f"No article container found on page: {url}")

    # Incrementally scroll to trigger lazy-loaded images
    scroll_height = await page.evaluate("document.body.scrollHeight")
    step = 600
    pos = 0
    while pos < scroll_height:
        pos = min(pos + step, scroll_height)
        await page.evaluate(f"window.scrollTo(0, {pos})")
        await page.wait_for_timeout(800)
        scroll_height = await page.evaluate("document.body.scrollHeight")
    await page.wait_for_timeout(3000)

    image_urls: list[str] = await page.evaluate(
        """(selector) => {
            const container = document.querySelector(selector);
            if (!container) return [];

            const seen = new Set();
            const results = [];

            // Collect video poster URLs to skip (document-wide)
            const videoPosterUrls = new Set();
            for (const el of document.querySelectorAll('video[poster]')) {
                videoPosterUrls.add(el.getAttribute('poster'));
            }

            // Skip images whose URL belongs to a video CDN or ad/sponsorship path
            const videoHostRe = /brightcove|bcsecure|jwplayer|ytimg|vimeocdn|cloudfront.*video|mux\\.com|video-stream/i;
            const skipPathRe = /\/sponsor(ship)?s?\//i;

            for (const img of container.querySelectorAll('img')) {
                const candidates = [
                    img.src,
                    img.getAttribute('data-src'),
                    img.getAttribute('data-lazy-src'),
                    img.getAttribute('data-original'),
                ];
                for (const src of candidates) {
                    if (!src || !src.startsWith('http') || seen.has(src)) continue;
                    if (videoPosterUrls.has(src) || videoHostRe.test(src) || skipPathRe.test(src)) continue;
                    const w = img.naturalWidth || parseInt(img.getAttribute('width') || '0');
                    if (w === 0 || w >= 300) {
                        seen.add(src);
                        results.push(src);
                    }
                }
            }
            return results;
        }""",
        matched_selector,
    )

    return text.strip(), title, image_urls


async def _download_image(client: httpx.AsyncClient, img_url: str, path: str) -> str | None:
    for attempt in range(3):
        try:
            resp = await client.get(img_url)
            resp.raise_for_status()
        except Exception:
            if attempt == 2:
                logger.warning("Failed to download image after 3 attempts: %s", img_url[:80])
                return None
            await asyncio.sleep(2)
            continue

        try:
            pil = PILImage.open(io.BytesIO(resp.content))
            w, h = pil.size
            pil.load()
        except Exception as e:
            logger.info("Skipping corrupt image %s: %s", img_url[:60], e)
            return None

        if w < _MIN_WIDTH or h < _MIN_HEIGHT:
            logger.info("Skipping small image %dx%d: %s", w, h, img_url[:60])
            return None

        pil.convert("RGB").save(path, "JPEG", quality=92)
        logger.info("Downloaded image (%dx%d): %s", w, h, img_url[:80])
        return path

    return None


async def scrape_article(url: str, cookies: list[dict], output_dir: str) -> ScrapedArticle:
    import shutil
    images_dir = os.path.join(output_dir, "images")
    if os.path.exists(images_dir):
        shutil.rmtree(images_dir)
    os.makedirs(images_dir)

    pw_cookies = _convert_cookies(cookies) if cookies else []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
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

    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [
            _download_image(client, img_url, os.path.join(images_dir, f"{i:03d}.jpg"))
            for i, img_url in enumerate(image_urls)
        ]
        results = await asyncio.gather(*tasks)

    image_paths = [r for r in results if r is not None]

    if not image_paths:
        raise ValueError(f"Failed to download any images for: {url}")

    return ScrapedArticle(title=title, link=url, full_text=full_text, image_paths=image_paths)
