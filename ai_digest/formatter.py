"""
formatter.py
Renders newsletter cards as a self-contained HTML file using a Jinja2 template.

Each card item must be a dict with:
  - title   (str)  : headline, may include emoji
  - summary (str)  : 2-sentence body
  - url     (str)  : "Read more" link
  - image_path (str | None) : path relative to output/ (e.g. "images/run_id/1.jpg")
                              or an absolute path — or empty/None if no image
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Template  # type: ignore[import-error]

from .storage import OUTPUT_DIR

# Path to the Jinja2 template file
_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "newsletter_card.html"


def _load_template() -> Template:
    return Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))


def _image_to_b64(image_path: str) -> tuple[str, str]:
    """
    Resolve `image_path` (relative to output/ or absolute), read it, and
    return (base64_string, mime_type).  Returns ("", "") on any failure.
    """
    if not image_path:
        return "", ""

    path = Path(image_path)

    # If relative, resolve against OUTPUT_DIR
    if not path.is_absolute():
        path = OUTPUT_DIR / image_path

    if not path.exists():
        return "", ""

    try:
        raw = path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "image/jpeg"
        return b64, mime
    except Exception:
        return "", ""


def render_newsletter_html(
    items: List[Dict[str, Any]],
    title: str,
    section_label: str,
    intro: Optional[str] = None,
    digest_headline: Optional[str] = None,
) -> str:
    """
    Render a list of card items into a self-contained HTML string.

    Each dict in `items` needs: title, summary, url, image_path.
    Base64 encoding happens here — the template receives image_b64 + image_mime.
    digest_headline: optional 1-sentence teaser shown in the masthead banner.
    """
    enriched = []
    for item in items:
        b64, mime = _image_to_b64(item.get("image_path") or "")
        enriched.append(
            {
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "url": item.get("url", ""),
                "image_b64": b64,
                "image_mime": mime,
            }
        )

    template = _load_template()
    return template.render(
        title=title,
        intro=intro,
        section_label=section_label,
        items=enriched,
        digest_headline=digest_headline,
    )