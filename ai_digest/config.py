from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path
from typing import List

from dotenv import load_dotenv  # type: ignore[import-error]

# All logs, run IDs, data timestamps, and output filenames use this timezone (UTC+8).
APP_TIMEZONE = timezone(timedelta(hours=8))
ACTIVE_CATEGORIES = ("ai_trends", "genai_tips", "ai_innovations", "ai_research")

# Load .env from cwd and from package dir (ai_digest/.env) so it works from project root
load_dotenv()
_package_dir = Path(__file__).resolve().parent
load_dotenv(_package_dir / ".env")


@dataclass
class Settings:
    openai_api_key: str
    openai_model: str
    openai_deep_research_model: str
    openai_deep_research_max_results: int
    openai_deep_research_max_tool_calls: int
    openai_deep_research_poll_interval_seconds: int
    openai_deep_research_timeout_seconds: int
    default_categories: List[str]
    collector_type: str  # "openai_deep_research" | "deep"
    deep_research_feeds: List[str]  # RSS/Atom feed URLs for deep collector


def _int_from_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(int(raw), minimum)
    except ValueError:
        return default


def get_settings() -> Settings:
    """
    Load configuration from environment variables (and optional .env file).
    """
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    collector_type = os.getenv("AI_DIGEST_COLLECTOR", "openai_deep_research").strip().lower()
    if collector_type in ("openai", "openai_deep", "api_deep_research"):
        collector_type = "openai_deep_research"
    if collector_type not in ("deep", "openai_deep_research"):
        collector_type = "openai_deep_research"

    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    openai_model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    openai_deep_research_model = os.getenv(
        "OPENAI_DEEP_RESEARCH_MODEL",
        "o4-mini-deep-research",
    ).strip()
    openai_deep_research_max_results = _int_from_env(
        "OPENAI_DEEP_RESEARCH_MAX_RESULTS",
        default=12,
        minimum=3,
    )
    openai_deep_research_max_tool_calls = _int_from_env(
        "OPENAI_DEEP_RESEARCH_MAX_TOOL_CALLS",
        default=24,
        minimum=5,
    )
    openai_deep_research_poll_interval_seconds = _int_from_env(
        "OPENAI_DEEP_RESEARCH_POLL_INTERVAL_SECONDS",
        default=15,
        minimum=2,
    )
    openai_deep_research_timeout_seconds = _int_from_env(
        "OPENAI_DEEP_RESEARCH_TIMEOUT_SECONDS",
        default=3600,
        minimum=60,
    )

    raw_categories = os.getenv("AI_DIGEST_CATEGORIES", ",".join(ACTIVE_CATEGORIES))
    default_categories = [
        c.strip()
        for c in raw_categories.split(",")
        if c.strip() in ACTIVE_CATEGORIES
    ]
    if not default_categories:
        default_categories = list(ACTIVE_CATEGORIES)

    raw_feeds = os.getenv("AI_DIGEST_DEEP_FEEDS", "")
    deep_research_feeds = [u.strip() for u in raw_feeds.split(",") if u.strip()]

    return Settings(
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        openai_deep_research_model=openai_deep_research_model,
        openai_deep_research_max_results=openai_deep_research_max_results,
        openai_deep_research_max_tool_calls=openai_deep_research_max_tool_calls,
        openai_deep_research_poll_interval_seconds=openai_deep_research_poll_interval_seconds,
        openai_deep_research_timeout_seconds=openai_deep_research_timeout_seconds,
        default_categories=default_categories,
        collector_type=collector_type,
        deep_research_feeds=deep_research_feeds,
    )
