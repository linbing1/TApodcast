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

    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(2000)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(500)

    image_urls: list[str] = await page.evaluate(
        """() => Array.from(document.querySelectorAll('img'))
            .filter(img => img.naturalWidth >= 300)
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
