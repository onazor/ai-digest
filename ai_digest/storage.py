from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .config import APP_TIMEZONE


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


def _default_serializer(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def save_run(run_payload: Dict[str, Any]) -> Path:
    """
    Save a full pipeline run to a timestamped JSON file under data/.
    """
    run_id = run_payload.get("run_id") or datetime.now(APP_TIMEZONE).strftime(
        "%Y%m%d-%H%M%S"
    )
    run_payload["run_id"] = run_id
    path = DATA_DIR / f"digest_run_{run_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(run_payload, f, ensure_ascii=False, indent=2, default=_default_serializer)
    return path


def load_latest_run() -> Optional[Dict[str, Any]]:
    """
    Load the most recently created run file from data/.
    """
    candidates = sorted(DATA_DIR.glob("digest_run_*.json"))
    if not candidates:
        return None
    latest = candidates[-1]
    with latest.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_newsletter_text(
    text: str,
    category: str,
    run_id: Optional[str] = None,
) -> Path:
    """
    Save a composed newsletter section to output/ as a text/Markdown file.
    """
    timestamp = datetime.now(APP_TIMEZONE).strftime("%Y%m%d-%H%M%S")
    safe_category = category.replace(" ", "_")
    if not run_id:
        run_id = timestamp
    path = OUTPUT_DIR / f"newsletter_{safe_category}_{run_id}.md"
    with path.open("w", encoding="utf-8") as f:
        f.write(text)
    return path



def save_newsletter_html(
    html: str,
    category: str,
    run_id: Optional[str] = None,
) -> Path:
    """
    Save a rendered HTML newsletter section to output/ as a self-contained .html file.
    """
    timestamp = datetime.now(APP_TIMEZONE).strftime("%Y%m%d-%H%M%S")
    safe_category = category.replace(" ", "_")
    if not run_id:
        run_id = timestamp
    path = OUTPUT_DIR / f"newsletter_{safe_category}_{run_id}.html"
    with path.open("w", encoding="utf-8") as f:
        f.write(html)
    return path