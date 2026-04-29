"""
Deep research collector: fetch from RSS/Atom feeds and optional web sources
instead of a single search API. Aligns with "Source Identification", "Crawling",
and "Parsing" steps for a continuous deep-search agent.
"""
from __future__ import annotations

import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    # arXiv & research — expanded for better ai_research coverage
    "https://rss.arxiv.org/rss/cs.AI",
    "https://rss.arxiv.org/rss/cs.LG",
    "https://rss.arxiv.org/rss/cs.CL",   # Computation & Language (NLP/LLMs)
    "https://rss.arxiv.org/rss/cs.CV",   # Computer Vision
    "https://rss.arxiv.org/rss/cs.NE",   # Neural & Evolutionary Computing
    "https://rss.arxiv.org/rss/cs.RO",   # Robotics
    "https://rss.arxiv.org/rss/stat.ML",
    "https://rss.arxiv.org/rss/cs.IR",   # Information Retrieval (RAG/search)
    "https://rss.arxiv.org/rss/eess.SP", # Signal Processing (audio/speech AI)
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

# Feeds used exclusively for ai_research_arxiv — only arXiv RSS feeds, nothing else.
ARXIV_ONLY_FEEDS = [
    "https://rss.arxiv.org/rss/cs.AI",
    "https://rss.arxiv.org/rss/cs.LG",
    "https://rss.arxiv.org/rss/cs.CL",
    "https://rss.arxiv.org/rss/cs.CV",
    "https://rss.arxiv.org/rss/cs.NE",
    "https://rss.arxiv.org/rss/cs.RO",
    "https://rss.arxiv.org/rss/stat.ML",
    "https://rss.arxiv.org/rss/cs.IR",
    "https://rss.arxiv.org/rss/eess.SP",
]

# Per-category keywords: if set, prefer entries that match. If no match or too few, we still use all entries.
CATEGORY_KEYWORDS = {
    "ai_trends": [
        "trend", "adoption", "surge", "growing", "rise", "shift", "report", "survey",
        "industry", "enterprise", "market", "widespread", "mainstream", "boom", "demand",
        "investment", "workforce", "jobs", "impact", "future", "regulation", "governance",
        "rollout", "deployment", "transformation", "disruption", "race", "competition",
        # tools/frameworks gaining traction (absorbed from tools_updates)
        "tool", "release", "update", "launch", "new version", "framework", "platform",
        "open source", "SDK", "API update", "integration",
    ],
    "ai_innovations": [
        # capability and model releases
        "GPT", "Gemini", "Claude", "Llama", "Mistral", "Grok", "model", "release", "launch",
        "benchmark", "capability", "performance", "multimodal", "reasoning", "agent",
        "long-context", "inference", "quantization", "fine-tuning", "open source", "weights",
        # architecture and technique advances
        "architecture", "transformer", "diffusion", "LoRA", "RLHF", "alignment",
        "neural", "training", "new model", "state-of-the-art", "SOTA", "outperforms",
        # major lab and company capability news
        "Google", "OpenAI", "Microsoft", "Meta", "Apple", "NVIDIA", "Anthropic",
        "announces", "introduces", "unveils", "breakthrough",
    ],
    "ai_research": [
        "arxiv", "paper", "preprint", "algorithm", "benchmark", "SOTA", "conference",
        "journal", "publication", "method", "result", "finding", "model", "training",
        "architecture", "NeurIPS", "ICML", "ICLR",
    ],
    "ai_research_arxiv": [],  # no keyword filter — URL filtering handles source restriction
    "genai_tips": [
        "prompt", "prompting", "chain-of-thought", "few-shot", "RAG", "agent", "LangChain",
        "LlamaIndex", "workflow", "pipeline", "technique", "framework", "evaluation", "evals",
        "fine-tuning", "embedding", "retrieval", "context window", "system prompt",
        "structured output", "function calling", "tool use", "notebook", "tutorial",
        "guide", "how to", "best practice", "practical", "hands-on", "walkthrough",
        "implementation", "API", "SDK",
    ],
    "ai_capability": [
        # Knowledge & search
        "knowledge assist", "knowledge management", "search", "enterprise search", "semantic search",
        "question answering", "chatbot", "virtual assistant", "copilot", "AI assistant",
        # Voice & speech
        "voice AI", "speech recognition", "text-to-speech", "speech synthesis", "voice agent",
        "voice assistant", "conversational AI", "natural language understanding", "ASR", "TTS",
        # Document & data processing
        "intelligent document processing", "IDP", "document understanding", "OCR",
        "document extraction", "data extraction", "form processing", "invoice processing",
        "contract analysis", "document AI",
        # Image & video generation
        "image generation", "video generation", "text-to-image", "text-to-video",
        "image editing", "video editing", "deepfake", "visual AI", "computer vision",
        "image recognition", "object detection", "image segmentation",
        # Code generation
        "code generation", "code completion", "code assistant", "coding AI", "AI coding",
        "program synthesis", "automated programming",
        # Other capabilities
        "translation", "summarization", "content generation", "text generation",
        "recommendation", "personalization", "predictive", "forecasting",
        "anomaly detection", "fraud detection", "automation", "RPA",
        "robotics", "autonomous", "self-driving", "AI agent", "agentic",
    ],
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


def _sort_arxiv_first(entries: List[dict]) -> List[dict]:
    """Sort arXiv entries to the top (by date), then all other entries (by date)."""
    arxiv = [e for e in entries if "arxiv.org" in (e.get("url") or "") or "arxiv" in (e.get("source") or "").lower()]
    others = [e for e in entries if e not in arxiv]
    return _sort_by_date(arxiv) + _sort_by_date(others)


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
    if category == "ai_research_arxiv":
        # Bypass user-configured feeds entirely — only arXiv RSS feeds
        feeds = ARXIV_ONLY_FEEDS
    else:
        feeds = settings.deep_research_feeds if settings.deep_research_feeds else DEFAULT_AI_FEEDS

    def _fetch_one(feed_url: str) -> Tuple[str, List[dict], str]:
        content, fetch_err = _fetch_feed_content(feed_url, timeout=25)
        if fetch_err:
            return (feed_url, [], fetch_err)
        try:
            entries = _parse_feed_content(content, feed_url)
            for e in entries:
                e["_feed_url"] = feed_url
            return (feed_url, entries, "")
        except Exception as parse_err:
            return (feed_url, [], str(parse_err))

    feed_map: dict = {}
    with ThreadPoolExecutor(max_workers=min(len(feeds), 20)) as pool:
        futures = {pool.submit(_fetch_one, url): url for url in feeds}
        for future in as_completed(futures):
            url, entries, err = future.result()
            feed_map[url] = (entries, err)

    # Reconstruct in original feed order so deduplication is deterministic
    all_entries: List[dict] = []
    feed_results: List[Tuple[str, int, str]] = []
    for feed_url in feeds:
        entries, err = feed_map.get(feed_url, ([], "not fetched"))
        feed_results.append((feed_url, len(entries), err))
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

    # Prefer recent articles (last 7 days, or 14 if too few).
    unique = _filter_recent(unique, max_results)

    # For ai_research: sort arXiv entries to the top so they aren't buried by general tech news.
    # For other categories: keyword filter with full-pool fallback.
    if category in ("ai_research", "ai_research_arxiv"):
        filtered = [e for e in unique if _matches_category(e, category)]
        if not filtered:
            filtered = unique
        # For ai_research_arxiv, additionally hard-filter to only arxiv.org URLs
        if category == "ai_research_arxiv":
            arxiv_only = [e for e in filtered if "arxiv.org" in (e.get("url") or "")]
            if arxiv_only:
                filtered = arxiv_only
        sorted_entries = _sort_arxiv_first(filtered)
    else:
        filtered = [e for e in unique if _matches_category(e, category)]
        if not filtered or len(filtered) < max_results:
            filtered = unique
        sorted_entries = _sort_by_date(filtered)

    to_take = sorted_entries[:max_results]

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