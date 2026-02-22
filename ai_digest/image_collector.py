"""
Collect one image per news article from the article's page (og:image or first suitable img),
save under output/images/<run_id>/ for easy scanning, and return a relative path for embedding.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urljoin

import requests  # pyright: ignore[reportMissingModuleSource]
from bs4 import BeautifulSoup  # pyright: ignore[reportMissingModuleSource]

from .storage import OUTPUT_DIR

IMAGES_DIR = OUTPUT_DIR / "images"
# User-Agent so some sites don't block us
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AI-Digest/1.0; +https://github.com/ai-digest)",
}

# Skip data URLs and tiny tracking pixels
MIN_IMAGE_WIDTH = 100
MIN_IMAGE_HEIGHT = 100


def _get_image_extension(content_type: str) -> str:
    if "png" in content_type:
        return "png"
    if "gif" in content_type:
        return "gif"
    if "webp" in content_type:
        return "webp"
    return "jpg"


def _absolute_url(base_url: str, src: str) -> str:
    if not src or src.startswith("data:"):
        return ""
    return urljoin(base_url, src.strip())


def _find_image_url(page_url: str, html: str) -> Optional[str]:
    """Extract best image URL from page: og:image first, then first large enough img."""
    soup = BeautifulSoup(html, "html.parser")
    # 1. Prefer og:image (social preview)
    meta = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if meta and meta.get("content"):
        return _absolute_url(page_url, meta["content"])
    # 2. twitter:image
    meta = soup.find("meta", attrs={"name": "twitter:image"})
    if meta and meta.get("content"):
        return _absolute_url(page_url, meta["content"])
    # 3. First img with decent src (prefer width/height if present)
    for img in soup.find_all("img"):
        src = img.get("src")
        if not src or "logo" in src.lower() or "icon" in src.lower() or "avatar" in src.lower():
            continue
        w = img.get("width")
        h = img.get("height")
        if w and h:
            try:
                if int(w) < MIN_IMAGE_WIDTH or int(h) < MIN_IMAGE_HEIGHT:
                    continue
            except (TypeError, ValueError):
                pass
        return _absolute_url(page_url, src)
    return None


def _download_image(image_url: str, timeout: int = 10) -> Tuple[Optional[bytes], str]:
    """Download image bytes; return (bytes or None, content_type)."""
    try:
        r = requests.get(image_url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "image/jpeg")
        return (r.content, ct)
    except Exception:
        return (None, "image/jpeg")


def collect_and_save_image(
    article_url: str,
    run_id: str,
    index: int,
    timeout: int = 10,
) -> Optional[str]:
    """
    Fetch the article page, find an image (og:image or first img), download it,
    and save under output/images/<run_id>/<index>.<ext>. Returns relative path
    from output/ (e.g. images/20260208-153640/1.jpg) for embedding, or None on failure.
    """
    if not article_url or not article_url.startswith("http"):
        return None
    run_dir = IMAGES_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        page = requests.get(article_url, headers=HEADERS, timeout=timeout)
        page.raise_for_status()
        image_url = _find_image_url(article_url, page.text)
        if not image_url:
            return None
        data, content_type = _download_image(image_url, timeout=timeout)
        if not data:
            return None
        ext = _get_image_extension(content_type)
        path = run_dir / f"{index}.{ext}"
        path.write_bytes(data)
        # Return path relative to output/ so newsletter can use images/run_id/1.jpg
        return f"images/{run_id}/{index}.{ext}"
    except Exception:
        return None
