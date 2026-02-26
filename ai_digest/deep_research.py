"""
Deep research collector: fetch from RSS/Atom feeds and optional web sources
instead of a single search API. Aligns with "Source Identification", "Crawling",
and "Parsing" steps for a continuous deep-search agent.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from .config import APP_TIMEZONE
from time import mktime
from typing import List, Tuple

import feedparser
import requests

# Only consider articles from the last N days (timely / likely still trending)
DEEP_RECENCY_DAYS_STRICT = 7
DEEP_RECENCY_DAYS_RELAXED = 14

logger = logging.getLogger(__name__)

from .agents import Article
from .config import get_settings

# Default AI news feeds (RSS/Atom). Override via AI_DIGEST_DEEP_FEEDS (comma-separated URLs).
# Large set for deep search; more feeds = more articles to choose from.
DEFAULT_AI_FEEDS = [
    # Mainstream tech
    "https://techcrunch.com/feed/",
    "https://venturebeat.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.wired.com/feed/rss",
    "https://www.theverge.com/tech/rss/index.xml",
    # AI / ML research & labs
    "https://openai.com/blog/rss.xml",
    "https://deepmind.google/blog/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://blogs.microsoft.com/ai/feed/",
    "https://blog.google/technology/developers/rss/",
    "https://engineering.fb.com/feed/",
    "https://feeds.feedburner.com/nvidiablog",
    # arXiv & research
    "https://rss.arxiv.org/rss/cs.AI",
    "https://rss.arxiv.org/rss/cs.LG",
    "https://rss.arxiv.org/rss/stat.ML",
    # AI/ML blogs & community
    "https://www.marktechpost.com/feed/",
    "https://syncedreview.com/feed/",
    "https://machinelearningmastery.com/feed/",
    "https://www.kdnuggets.com/feed",
    "https://huggingface.co/blog/feed.xml",
    "https://pytorch.org/feed/",
    "https://blog.tensorflow.org/feeds/posts/default",
    # Tech news & reviews
    "https://www.technologyreview.com/feed/",
    "https://www.engadget.com/rss.xml",
    "https://www.cnet.com/rss/news/",
    "https://www.zdnet.com/news/rss.xml",
    # Startup / product & research
    "https://www.anthropic.com/news/rss.xml",
    "https://blog.cohere.com/rss.xml",
    "https://news.mit.edu/topic/artificial-intelligence2/feed",
    "https://www.infoq.com/ai-ml/news/feed/",
]

# Per-category keywords: if set, prefer entries that match. If no match or too few, we still use all entries.
CATEGORY_KEYWORDS = {
    "ai_trends": [],
    "ai_technology": ["Google", "Apple", "Microsoft", "OpenAI", "Meta", "Amazon", "NVIDIA", "tech", "product", "launch", "company", "announces"],
    "ai_innovations": ["model", "algorithm", "research", "paper", "arXiv", "ML", "training", "inference", "architecture", "neural", "learning", "AI"],
    "ai_research": ["arxiv", "paper", "preprint", "algorithm", "benchmark", "SOTA", "conference", "journal", "publication", "method", "result", "finding", "model", "training", "architecture", "NeurIPS", "ICML", "ICLR"],
    "genai_tips": ["tip", "how to", "guide", "tutorial", "best practice", "use", "prompt", "GenAI", "generative"],
    "tools_updates": ["tool", "release", "update", "API", "software", "launch", "new", "version"],
    "policy_ethics": ["policy", "regulation", "ethics", "law", "EU", "US", "governance", "legal", "bill", "AI act"],
}


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities for cleaner snippet/content."""
    if not text:
        return ""
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-error]
        soup = BeautifulSoup(text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


def _fetch_feed_content(url: str, timeout: int = 25) -> Tuple[str, str]:
    """
    Fetch raw feed content with requests (more reliable than feedparser's built-in fetch).
    Returns (content, error_message). error_message is empty on success.
    """
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Digest/1.0; newsletter aggregation)"},
            timeout=timeout,
            allow_redirects=True,
        )
        r.raise_for_status()
        return (r.text, "")
    except requests.RequestException as e:
        return ("", str(e))
    except Exception as e:
        return ("", str(e))


def _parse_feed_content(content: str, feed_url: str) -> List[dict]:
    """Parse RSS/Atom XML content into entry dicts. Uses feed_url for source when feed title is missing."""
    parsed = feedparser.parse(content)
    entries = []
    for e in getattr(parsed, "entries", []):
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not link:
            continue
        summary = e.get("summary") or e.get("description") or ""
        if hasattr(summary, "value"):
            summary = summary.value
        summary = _strip_html((summary or "").strip())[:5000]
        if not summary and title:
            summary = title
        published = e.get("published_parsed") or e.get("updated_parsed")
        source = getattr(parsed.feed, "title", feed_url) if hasattr(parsed, "feed") and parsed.feed else feed_url
        entries.append({
            "title": title or "(no title)",
            "url": link,
            "snippet": summary[:4000],
            "content": summary,
            "source": source,
            "published_parsed": published,
        })
    return entries


def _parse_feed(url: str, timeout: int = 25) -> List[dict]:
    """Fetch and parse one RSS/Atom feed; return list of entry dicts."""
    content, fetch_error = _fetch_feed_content(url, timeout=timeout)
    if fetch_error:
        logger.debug("Feed fetch failed %s: %s", url, fetch_error)
        return []
    try:
        return _parse_feed_content(content, url)
    except Exception as err:
        logger.debug("Feed parse failed %s: %s", url, err)
        return []


def _matches_category(entry: dict, category: str) -> bool:
    """True if entry is relevant to category (keyword filter if defined)."""
    keywords = CATEGORY_KEYWORDS.get(category, [])
    if not keywords:
        return True
    text = (entry.get("title") or "") + " " + (entry.get("snippet") or "") + " " + (entry.get("content") or "")
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in keywords)


def _sort_by_date(entries: List[dict]) -> List[dict]:
    """Sort by published_parsed (newest first); entries without date go last."""
    def key(e):
        p = e.get("published_parsed")
        if p:
            try:
                return -mktime(p)
            except Exception:
                pass
        return 0
    return sorted(entries, key=key)


def _within_days(entry: dict, days: int) -> bool:
    """True if entry has a published date within the last `days` days."""
    p = entry.get("published_parsed")
    if not p:
        return False
    try:
        pub_ts = mktime(p)
        pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc)
        cutoff = datetime.now(APP_TIMEZONE) - timedelta(days=days)
        # Compare in same tz: convert pub_dt to APP_TIMEZONE for cutoff comparison
        pub_dt = pub_dt.astimezone(APP_TIMEZONE)
        return pub_dt >= cutoff
    except Exception:
        return False


def _filter_recent(
    entries: List[dict],
    max_results: int,
    strict_days: int = DEEP_RECENCY_DAYS_STRICT,
    relaxed_days: int = DEEP_RECENCY_DAYS_RELAXED,
) -> List[dict]:
    """
    Keep only timely entries (last 7 days, or 14 if too few).
    Ensures we prioritize recent / likely-trending news.
    """
    recent_strict = [e for e in entries if _within_days(e, strict_days)]
    if len(recent_strict) >= max_results:
        return recent_strict
    recent_relaxed = [e for e in entries if _within_days(e, relaxed_days)]
    return recent_relaxed if recent_relaxed else entries


def collect_articles_for_category(
    category: str,
    max_results: int = 6,
) -> List[Article]:
    """
    Deep research collector: fetch from configured RSS/Atom feeds, filter by category
    keywords, sort by date, and return up to max_results Articles. No Tavily dependency.
    """
    settings = get_settings()
    feeds = settings.deep_research_feeds if settings.deep_research_feeds else DEFAULT_AI_FEEDS

    all_entries: List[dict] = []
    feed_results: List[Tuple[str, int, str]] = []  # (url, count, error)
    for feed_url in feeds:
        content, fetch_err = _fetch_feed_content(feed_url, timeout=25)
        if fetch_err:
            feed_results.append((feed_url, 0, fetch_err))
            continue
        try:
            entries = _parse_feed_content(content, feed_url)
        except Exception as parse_err:
            feed_results.append((feed_url, 0, str(parse_err)))
            continue
        feed_results.append((feed_url, len(entries), ""))
        for e in entries:
            e["_feed_url"] = feed_url
        all_entries.extend(entries)

    # Dedupe by URL
    seen_urls = set()
    unique = []
    for e in all_entries:
        u = (e.get("url") or "").strip()
        if u and u not in seen_urls:
            seen_urls.add(u)
            unique.append(e)

    if not unique:
        ok = sum(1 for _, n, err in feed_results if n > 0)
        failed = len(feed_results) - ok
        msg = (
            f"Deep research: 0 articles from {len(feeds)} feeds ({ok} ok, {failed} failed/empty). "
            "Check network and feed URLs."
        )
        logger.warning(msg)
        print(f"[deep research] {msg}")
        for url, count, err in feed_results[:8]:
            short = url[:60] + "..." if len(url) > 60 else url
            print(f"  - {short} -> {count} entries" + (f" ({err})" if err else ""))
        if len(feed_results) > 8:
            print(f"  ... and {len(feed_results) - 8} more feeds.")

    # Prefer recent articles (last 7 days, or 14 if too few) so we surface timely / likely-trending news
    unique = _filter_recent(unique, max_results)

    # Prefer entries matching category keywords; if too few, use all (so every category gets a full pool).
    filtered = [e for e in unique if _matches_category(e, category)]
    if not filtered or len(filtered) < max_results:
        filtered = unique

    sorted_entries = _sort_by_date(filtered)
    # Return more articles for deep search so the quality agent has a larger pool (more likely some pass)
    take = min(max_results * 2, 30)
    to_take = sorted_entries[:take]

    now = datetime.now(APP_TIMEZONE).isoformat()
    articles: List[Article] = []
    for e in to_take:
        articles.append(
            Article(
                id=str(uuid.uuid4()),
                category=category,
                title=e.get("title") or "(no title)",
                url=e.get("url") or "",
                snippet=e.get("snippet") or "",
                content=e.get("content") or e.get("snippet") or "",
                source=e.get("source", "deep_research"),
                collected_at=now,
            )
        )
    return articles
