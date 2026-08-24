import os
import re
from datetime import date
from urllib.parse import urlparse


def article_slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    parts = [part for part in path.split("/") if part]
    slug = parts[-1] if parts else "article"
    return slug[:60]


def safe_title(title: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()[:40]


def default_output_dir(url: str) -> str:
    return os.path.join("output", str(date.today()), article_slug(url))
