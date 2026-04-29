from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path
from typing import List

from dotenv import load_dotenv  # type: ignore[import-error]

# All logs, run IDs, data timestamps, and output filenames use this timezone (UTC+8).
APP_TIMEZONE = timezone(timedelta(hours=8))

# Load .env from cwd and from package dir (ai_digest/.env) so it works from project root
load_dotenv()
_package_dir = Path(__file__).resolve().parent
load_dotenv(_package_dir / ".env")


@dataclass
class Settings:
    openai_api_key: str
    openai_model: str
    tavily_api_key: str
    default_categories: List[str]
    collector_type: str  # "tavily" | "deep" | "both"
    deep_research_feeds: List[str]  # RSS/Atom feed URLs for deep collector


def get_settings() -> Settings:
    """
    Load configuration from environment variables (and optional .env file).
    """
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    tavily_api_key = os.environ.get("TAVILY_API_KEY")
    collector_type = os.getenv("AI_DIGEST_COLLECTOR", "tavily").strip().lower()
    if collector_type not in ("tavily", "deep", "both"):
        collector_type = "tavily"

    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    if collector_type in ("tavily", "both") and not tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY is not set when using Tavily (or both) collector.")

    openai_model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    raw_categories = os.getenv(
        "AI_DIGEST_CATEGORIES",
        "ai_trends,genai_tips,ai_innovations,ai_research,ai_research_arxiv,ai_capability",
    )
    default_categories = [c.strip() for c in raw_categories.split(",") if c.strip()]

    raw_feeds = os.getenv("AI_DIGEST_DEEP_FEEDS", "")
    deep_research_feeds = [u.strip() for u in raw_feeds.split(",") if u.strip()]

    return Settings(
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        tavily_api_key=tavily_api_key or "",
        default_categories=default_categories,
        collector_type=collector_type,
        deep_research_feeds=deep_research_feeds,
    )