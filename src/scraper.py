import asyncio
import io
import json
import logging
import os
import shutil
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from PIL import Image as PILImage
from playwright.async_api import Page, async_playwright

from src.models import ImageAsset, PageContent, ScrapedArticle, VideoAsset

_MIN_WIDTH = 600
_MIN_HEIGHT = 300
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

logger = logging.getLogger(__name__)

_ARTICLE_SELECTORS = [
    "[class*='Article_ContentContainer']",
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


def _normalize_text(text: str) -> str:
    lines: list[str] = []
    previous_blank = False
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = " ".join(raw_line.split())
        if line:
            lines.append(line)
            previous_blank = False
        elif lines and not previous_blank:
            lines.append("")
            previous_blank = True
    return "\n".join(lines).strip()


def _clean_main_text(text: str) -> str:
    lines = _normalize_text(text).split("\n")
    noise_headings = {
        "WHAT YOU SHOULD READ NEXT",
        "YOUR NEXT READ",
        "LATEST LEAGUE STORIES",
        "LATEST HEADLINES",
    }
    clean_lines: list[str] = []
    skipping_related = False
    for line in lines:
        if line.strip().upper() in noise_headings:
            skipping_related = True
            continue
        if skipping_related:
            if not line.strip():
                skipping_related = False
            continue
        clean_lines.append(line)
    return _normalize_text("\n".join(clean_lines))


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _image_key(url: str) -> str:
    parts = urlsplit(url)
    transform_params = {
        "auto",
        "crop",
        "fit",
        "fm",
        "format",
        "h",
        "height",
        "q",
        "quality",
        "w",
        "width",
    }
    query = urlencode([
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in transform_params
    ])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


def _jsonld_nodes(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from _jsonld_nodes(item)
        return
    if not isinstance(value, dict):
        return
    yield value
    if "@graph" in value:
        yield from _jsonld_nodes(value["@graph"])


def _jsonld_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "text"):
            if isinstance(value.get(key), str):
                return value[key].strip()
    return ""


def _jsonld_image_candidates(value: Any, base_url: str):
    if isinstance(value, list):
        for item in value:
            yield from _jsonld_image_candidates(item, base_url)
        return
    if isinstance(value, str):
        absolute = urljoin(base_url, value.strip())
        if absolute:
            yield ImageAsset(url=absolute)
        return
    if not isinstance(value, dict):
        return

    raw_types = value.get("@type", [])
    types = {raw_types} if isinstance(raw_types, str) else set(raw_types)
    if "VideoObject" in types:
        return

    raw_url = value.get("contentUrl") or value.get("url")
    if isinstance(raw_url, dict):
        raw_url = raw_url.get("url") or raw_url.get("@id")
    if not isinstance(raw_url, str) or not raw_url.strip():
        return

    caption = _jsonld_text(value.get("caption"))
    alternate_name = _jsonld_text(value.get("alternateName"))
    credit = _jsonld_text(value.get("creditText"))
    if not credit:
        credit = _jsonld_text(value.get("creator")) or _jsonld_text(
            value.get("copyrightHolder")
        )
    yield ImageAsset(
        url=urljoin(base_url, raw_url.strip()),
        alt=alternate_name or caption or _jsonld_text(value.get("name")),
        caption=caption,
        credit=credit,
        width=_to_int(value.get("width")),
        height=_to_int(value.get("height")),
    )


def _extract_jsonld_images(raw_scripts: list[str], base_url: str) -> list[ImageAsset]:
    images: list[ImageAsset] = []
    seen: set[str] = set()
    article_types = {"Article", "BlogPosting", "NewsArticle", "ReportageNewsArticle"}

    for raw_script in raw_scripts:
        try:
            parsed = json.loads(raw_script)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _jsonld_nodes(parsed):
            raw_types = item.get("@type", [])
            types = {raw_types} if isinstance(raw_types, str) else set(raw_types)
            if not types.intersection(article_types):
                continue
            for field in ("image", "primaryImageOfPage", "associatedMedia", "thumbnailUrl"):
                for image in _jsonld_image_candidates(item.get(field), base_url):
                    key = _image_key(image.url)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    images.append(image)
    return images


def _merge_images(*image_groups: list[ImageAsset]) -> list[ImageAsset]:
    images: list[ImageAsset] = []
    by_key: dict[str, ImageAsset] = {}
    for group in image_groups:
        for image in group:
            key = _image_key(image.url)
            if not key:
                continue
            existing = by_key.get(key)
            if existing:
                if not existing.alt:
                    existing.alt = image.alt
                if not existing.caption:
                    existing.caption = image.caption
                if not existing.credit:
                    existing.credit = image.credit
                if not existing.width:
                    existing.width = image.width
                if not existing.height:
                    existing.height = image.height
                continue
            by_key[key] = image
            images.append(image)
    return images


def _find_cover_image_index(images: list[ImageAsset], cover_url: str) -> int | None:
    if not images:
        return None
    if cover_url:
        cover_key = _image_key(cover_url)
        for index, image in enumerate(images):
            if _image_key(image.url) == cover_key:
                return index
    return 0


def _select_cover_image(
    images: list[ImageAsset],
    metadata_url: str,
    positional_url: str,
) -> tuple[int | None, str]:
    if not images:
        return None, ""

    for candidate in (metadata_url, positional_url):
        if not candidate:
            continue
        candidate_key = _image_key(candidate)
        for index, image in enumerate(images):
            if _image_key(image.url) == candidate_key:
                return index, candidate

    return 0, images[0].url


async def _extract_page_content_data(page: Page, url: str) -> PageContent:
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
            if len(_normalize_text(await element.inner_text())) > 100:
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

    element = await page.query_selector(matched_selector)
    text = _clean_main_text(
        await element.evaluate(
            """(element) => {
                const clone = element.cloneNode(true);
                clone.querySelectorAll('script, style, noscript, nav, aside, form, button, [aria-hidden="true"], [class*="ImageCaption"], [class*="ImageCredit"], [class*="Related"], [class*="Recommendation"], [class*="Share"]').forEach((node) => node.remove());
                clone.querySelectorAll('*').forEach((node) => {
                    if (!node.children.length && node.textContent.trim() === 'Advertisement') {
                        node.remove();
                    }
                });
                clone.style.position = 'absolute';
                clone.style.left = '-100000px';
                clone.style.width = '1000px';
                document.body.appendChild(clone);
                const text = clone.innerText;
                clone.remove();
                return text;
            }"""
        )
    )

    media: dict[str, Any] = await page.evaluate(
        """(selector) => {
            const container = document.querySelector(selector);
            if (!container) return {images: [], videos: [], coverImageUrl: ""};
            const mediaRoots = [container];
            const featuredContainer = document.querySelector('[class*="FeaturedImageContainer"]');
            if (featuredContainer && featuredContainer !== container) mediaRoots.push(featuredContainer);

            const seenImages = new Set();
            const seenVideos = new Set();
            const images = [];
            const videos = [];
            const headings = Array.from(document.querySelectorAll(
                'h1, [role="heading"][aria-level="1"], [class*="Headline"], [class*="headline"]'
            ));
            const heading = headings.find((candidate) => {
                const rect = candidate.getBoundingClientRect();
                return candidate.textContent.trim() && rect.width > 0 && rect.height > 0;
            });
            const headingRect = heading ? heading.getBoundingClientRect() : null;
            const headingTop = headingRect ? headingRect.top + window.scrollY : null;
            const headingBottom = headingRect ? headingRect.bottom + window.scrollY : null;
            const absoluteUrl = (value) => {
                if (!value) return "";
                try { return new URL(value, document.baseURI).href; }
                catch (_) { return ""; }
            };
            const metadataCoverImageUrl = absoluteUrl(
                document.querySelector('meta[property="og:image"]')?.getAttribute('content') ||
                document.querySelector('meta[name="twitter:image"]')?.getAttribute('content')
            );
            const addVideo = (video) => {
                if (!video.url || seenVideos.has(video.url)) return;
                seenVideos.add(video.url);
                videos.push(video);
            };

            const videoPosterUrls = new Set();
            for (const el of document.querySelectorAll('video[poster]')) {
                const poster = absoluteUrl(el.getAttribute('poster'));
                if (poster) videoPosterUrls.add(poster);
            }

            const videoHostRe = /brightcove|bcsecure|jwplayer|ytimg|vimeocdn|cloudfront.*video|mux\\.com|video-stream/i;
            const skipPathRe = new RegExp("/sponsor(ship)?s?/", "i");

            for (const root of mediaRoots) {
                for (const img of root.querySelectorAll('img')) {
                if (img.closest('a.showcase-link-container, a.in-content-module-link, [class*="Related"], [class*="Recommendation"]')) continue;
                const candidates = [
                    img.currentSrc,
                    img.getAttribute('data-src'),
                    img.getAttribute('data-lazy-src'),
                    img.getAttribute('data-original'),
                    img.src,
                ];
                for (const src of candidates) {
                    const absolute = absoluteUrl(src);
                    if (!absolute || seenImages.has(absolute)) continue;
                    if (videoPosterUrls.has(absolute) || videoHostRe.test(absolute) || skipPathRe.test(absolute)) continue;
                    const w = img.naturalWidth || parseInt(img.getAttribute('width') || '0');
                    if (w === 0 || w >= 300) {
                        const rect = img.getBoundingClientRect();
                        const imageTop = rect.top + window.scrollY;
                        const imageBottom = rect.bottom + window.scrollY;
                        let headingDistance = imageTop;
                        if (headingTop !== null && headingBottom !== null) {
                            if (imageBottom <= headingTop) {
                                headingDistance = headingTop - imageBottom;
                            } else if (imageTop >= headingBottom) {
                                headingDistance = imageTop - headingBottom;
                            } else {
                                headingDistance = 0;
                            }
                        }
                        seenImages.add(absolute);
                        images.push({
                            url: absolute,
                            alt: img.getAttribute('alt') || '',
                            width: w || null,
                            height: img.naturalHeight || parseInt(img.getAttribute('height') || '0') || null,
                            headingDistance,
                            imageTop,
                        });
                        break;
                    }
                }
            }
            }

            for (const root of mediaRoots) {
                for (const video of root.querySelectorAll('video')) {
                const poster = absoluteUrl(video.getAttribute('poster'));
                const sources = [
                    video.getAttribute('src'),
                    ...Array.from(video.querySelectorAll('source')).map((source) => source.getAttribute('src')),
                ];
                for (const src of sources) {
                    addVideo({
                        url: absoluteUrl(src),
                        kind: 'video',
                        poster,
                        title: video.getAttribute('title') || '',
                        width: video.videoWidth || null,
                        height: video.videoHeight || null,
                        duration: Number.isFinite(video.duration) ? String(video.duration) : null,
                    });
                }
            }
            }

            for (const root of mediaRoots) {
                for (const iframe of root.querySelectorAll('iframe[src]')) {
                const iframeUrl = absoluteUrl(iframe.getAttribute('src'));
                if (iframeUrl && /youtube|youtu\\.be|vimeo|brightcove|jwplayer|player|video|stream|embed/i.test(iframeUrl)) {
                    addVideo({
                        url: iframeUrl,
                        kind: 'iframe',
                        poster: '',
                        title: iframe.getAttribute('title') || '',
                        width: parseInt(iframe.getAttribute('width') || '0') || null,
                        height: parseInt(iframe.getAttribute('height') || '0') || null,
                        duration: null,
                    });
                }
            }
            }

            for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
                try {
                    const parsed = JSON.parse(script.textContent || 'null');
                    const roots = Array.isArray(parsed) ? parsed : [parsed];
                    const items = roots.flatMap((value) => {
                        if (!value) return [];
                        return value['@graph'] || [value];
                    });
                    for (const item of items) {
                        const types = Array.isArray(item['@type']) ? item['@type'] : [item['@type']];
                        if (!types.includes('VideoObject')) continue;
                        const videoUrl = absoluteUrl(item.contentUrl || item.embedUrl || item.url);
                        if (videoUrl) {
                            addVideo({
                                url: videoUrl,
                                kind: 'jsonld',
                                poster: absoluteUrl(item.thumbnailUrl),
                                title: item.name || '',
                                width: item.width || null,
                                height: item.height || null,
                                duration: item.duration || null,
                            });
                        }
                    }
                } catch (_) {}
            }

            const rankedImages = images.slice().sort((left, right) => {
                if (left.headingDistance !== right.headingDistance) {
                    return left.headingDistance - right.headingDistance;
                }
                return left.imageTop - right.imageTop;
            });
            const positionCoverImageUrl = rankedImages[0]?.url || images[0]?.url || '';
            const jsonLd = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                .map((script) => script.textContent || '');
            return {images, videos, jsonLd, metadataCoverImageUrl, positionCoverImageUrl};
        }""",
        matched_selector,
    )

    dom_images = [
        ImageAsset(
            url=item["url"],
            alt=item.get("alt", ""),
            width=_to_int(item.get("width")),
            height=_to_int(item.get("height")),
        )
        for item in media.get("images", [])
    ]
    jsonld_images = _extract_jsonld_images(media.get("jsonLd", []), url)
    images = _merge_images(jsonld_images, dom_images)
    cover_image_index, cover_image_url = _select_cover_image(
        images,
        media.get("metadataCoverImageUrl", ""),
        media.get("positionCoverImageUrl", ""),
    )
    videos = [
        VideoAsset(
            url=item["url"],
            kind=item.get("kind", "video"),
            poster=item.get("poster", ""),
            title=item.get("title", ""),
            width=_to_int(item.get("width")),
            height=_to_int(item.get("height")),
            duration=item.get("duration"),
        )
        for item in media.get("videos", [])
        if item.get("url")
    ]
    return PageContent(
        url=url,
        title=title.strip(),
        main_text=text,
        images=images,
        videos=videos,
        cover_image_index=cover_image_index,
        cover_image_url=cover_image_url,
    )


async def extract_page_content(url: str, cookies: list[dict]) -> PageContent:
    pw_cookies = _convert_cookies(cookies) if cookies else []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                _USER_AGENT
            )
        )
        if pw_cookies:
            await context.add_cookies(pw_cookies)
        page = await context.new_page()
        try:
            return await _extract_page_content_data(page, url)
        finally:
            await page.close()
            await browser.close()


def _cookie_header(raw_cookies: list[dict]) -> str:
    return "; ".join(
        f"{cookie['name']}={cookie['value']}"
        for cookie in raw_cookies
        if cookie.get("name") and cookie.get("value") is not None
    )


async def _download_image(
    client: httpx.AsyncClient,
    img_url: str,
    path: str,
    headers: dict[str, str] | None = None,
) -> str | None:
    for attempt in range(3):
        try:
            resp = await client.get(img_url, headers=headers)
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


async def download_images(
    images: list[ImageAsset],
    output_dir: str,
    referer: str = "",
    cookies: list[dict] | None = None,
    cover_image_index: int | None = None,
) -> list[dict[str, Any]]:
    images_dir = os.path.join(output_dir, "images")
    if os.path.exists(images_dir):
        shutil.rmtree(images_dir)
    os.makedirs(images_dir, exist_ok=True)

    headers = {"User-Agent": _USER_AGENT}
    if referer:
        headers["Referer"] = referer
    cookie_value = _cookie_header(cookies or [])
    if cookie_value:
        headers["Cookie"] = cookie_value

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        async def download_one(index: int, image: ImageAsset) -> dict[str, Any]:
            relative_path = os.path.join("images", f"{index:03d}.jpg")
            absolute_path = os.path.join(output_dir, relative_path)
            local_path = await _download_image(client, image.url, absolute_path, headers=headers)
            record: dict[str, Any] = {
                "url": image.url,
                "local_path": relative_path,
                "status": "downloaded" if local_path else "failed",
                "error": None if local_path else "download failed after 3 attempts",
                "alt": image.alt,
                "caption": image.caption,
                "credit": image.credit,
                "width": image.width,
                "height": image.height,
                "is_cover": index == cover_image_index,
            }
            return record

        records = await asyncio.gather(
            *(download_one(index, image) for index, image in enumerate(images))
        )

    downloaded = sum(record["status"] == "downloaded" for record in records)
    logger.info("Downloaded %d/%d images to %s", downloaded, len(records), images_dir)
    return records


async def scrape_article(url: str, cookies: list[dict], output_dir: str) -> ScrapedArticle:
    content = await extract_page_content(url, cookies)
    title = content.title
    full_text = content.main_text

    if not content.images:
        raise ValueError(f"No images found in article: {url}")

    records = await download_images(
        content.images,
        output_dir,
        referer=url,
        cookies=cookies,
        cover_image_index=content.cover_image_index,
    )
    image_paths = [
        os.path.join(output_dir, record["local_path"])
        for record in records
        if record["status"] == "downloaded"
    ]

    if not image_paths:
        raise ValueError(f"Failed to download any images for: {url}")

    cover_image_path = None
    if content.cover_image_index is not None and content.cover_image_index < len(records):
        cover_record = records[content.cover_image_index]
        if cover_record["status"] == "downloaded":
            cover_image_path = os.path.join(output_dir, cover_record["local_path"])
    with open(os.path.join(output_dir, "cover.json"), "w", encoding="utf-8") as cover_file:
        json.dump(
            {
                "image_index": content.cover_image_index,
                "image_url": content.cover_image_url,
                "local_path": (
                    os.path.relpath(cover_image_path, output_dir)
                    if cover_image_path else None
                ),
            },
            cover_file,
            ensure_ascii=False,
            indent=2,
        )

    return ScrapedArticle(
        title=title,
        link=url,
        full_text=full_text,
        image_paths=image_paths,
        cover_image_path=cover_image_path,
    )
