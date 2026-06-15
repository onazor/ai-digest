"""
OpenAI Deep Research collector.

This collector uses the Responses API with the dedicated deep research models
instead of the local RSS/feed approximation in deep_research.py.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List

from openai import OpenAI  # type: ignore[import-error]

from .agents import Article
from .config import APP_TIMEZONE, get_settings


logger = logging.getLogger(__name__)

RATE_LIMIT_RETRY_DELAYS_SECONDS = (20, 45, 90)


CATEGORY_BRIEFS: Dict[str, str] = {
    "ai_trends": (
        "Trending AI news in general, including broad AI/GenAI trends, adoption shifts, "
        "enterprise rollouts, analyst/survey findings, regulation/governance movements, "
        "workforce impact, market behavior, and widely discussed AI topics. This category "
        "is about what is gaining attention or traction across the industry. Exclude "
        "how-to/tutorial content (genai_tips), model/product breakthroughs centered on "
        "a new capability (ai_innovations), and theory-heavy papers or journals "
        "(ai_research)."
    ),
    "ai_innovations": (
        "New innovations happening in AI: model releases, agentic systems, multimodal "
        "features, reasoning improvements, open-source model or framework milestones, "
        "benchmark-backed capability jumps, major AI product capabilities, and new "
        "technical features from labs or vendors. This category is about what is newly "
        "possible. Exclude general trend/adoption stories (ai_trends), practical tips "
        "or tutorials (genai_tips), and theory-heavy papers without a released or "
        "deployable innovation angle (ai_research)."
    ),
    "ai_research": (
        "Research papers exclusively, plus journal articles or theory-heavy technical "
        "articles about AI. Prioritize papers, preprints, conference work, journals, "
        "benchmarks, novel architectures, algorithms, evaluations, formal research "
        "results, and articles whose primary value is theoretical or methodological. "
        "Exclude product launches (ai_innovations), trend/adoption coverage (ai_trends), "
        "and practical how-to guides or tooling tutorials (genai_tips)."
    ),
    "genai_tips": (
        "Practical tips about using GenAI, including techniques, tools, workflows, "
        "prompting patterns, RAG/agent/evaluation workflows, API/tooling guidance, "
        "implementation walkthroughs, and applied lessons for practitioners. This category "
        "is about how to use GenAI better. Exclude general AI news/trends (ai_trends), "
        "new AI capability announcements (ai_innovations), and research papers or "
        "theory-heavy articles (ai_research)."
    ),
}


def _build_research_prompt(category: str, max_results: int) -> str:
    category_brief = CATEGORY_BRIEFS.get(
        category,
        f"Important recent AI and generative AI stories for category '{category}'.",
    )
    research_rule = (
        "For ai_research, sources must be research papers, preprints, journals, conference pages, or theory-heavy technical articles."
        if category == "ai_research"
        else "Do not return research papers, journals, arXiv/preprint items, or theory-heavy articles unless they are only being cited as context, not selected as items."
    )

    return f"""
Research current AI news and resources for an internal AI Digest newsletter.

Category: {category}
Category brief: {category_brief}
Audience: AI practitioners and leaders at a bank.
Time window: prioritize the last 7 days; use up to 14 days only if needed for quality.

Selection rules:
- Return exactly {max_results} distinct items if enough high-quality items exist.
- Prefer primary sources, reputable technology/business press, research venues, and official company blogs.
- Each item must clearly match the category brief; reject same-story duplicates.
- Treat the four categories as mutually exclusive: ai_trends = broad trending news, genai_tips = practical usage techniques/tools, ai_innovations = new AI capabilities or inventions, ai_research = papers/journals/theory-heavy work.
- If an item could fit multiple categories, choose the single category where its primary value belongs. Return it only if that primary category is "{category}".
- {research_rule}
- Favor specific, source-backed developments over generic AI commentary.
- Include source URLs that are publicly reachable and suitable for newsletter citations.

Return only valid JSON, with no Markdown fences and no commentary. Use this schema:
{{
  "articles": [
    {{
      "title": "specific article or paper title",
      "url": "https://...",
      "source": "publisher or organization name",
      "published_date": "YYYY-MM-DD or unknown",
      "snippet": "one concise sentence describing the source",
      "why_it_fits": "why this belongs in the requested category",
      "key_points": ["specific fact, number, feature, or claim", "another concrete point"],
      "summary": "2 sentence newsletter-ready summary with the main implication"
    }}
  ]
}}
""".strip()


def _extract_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text).strip()

    chunks: List[str] = []
    for item in getattr(response, "output", []) or []:
        item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
        if item_type != "message":
            continue
        contents = item.get("content", []) if isinstance(item, dict) else getattr(item, "content", [])
        for content in contents or []:
            text = content.get("text") if isinstance(content, dict) else getattr(content, "text", None)
            if text:
                chunks.append(str(text))
    return "\n".join(chunks).strip()


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    return cleaned


def _parse_articles_json(text: str) -> List[Dict[str, Any]]:
    cleaned = _strip_json_fence(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(cleaned[start : end + 1])

    if isinstance(data, list):
        articles = data
    else:
        articles = data.get("articles", [])

    if not isinstance(articles, list):
        return []
    return [a for a in articles if isinstance(a, dict)]


def _wait_for_response(client: OpenAI, response: Any, timeout_seconds: int, poll_interval: int) -> Any:
    deadline = time.monotonic() + timeout_seconds
    current = response
    while getattr(current, "status", None) in ("queued", "in_progress"):
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"OpenAI Deep Research did not finish within {timeout_seconds} seconds."
            )
        time.sleep(poll_interval)
        current = client.responses.retrieve(getattr(current, "id"))
    return current


def _response_error_text(response: Any) -> str:
    error = getattr(response, "error", None)
    if error is None:
        return ""
    code = getattr(error, "code", "")
    message = getattr(error, "message", "")
    if isinstance(error, dict):
        code = error.get("code", code)
        message = error.get("message", message)
    return f"{code} {message}".strip()


def _is_rate_limit_response(response: Any) -> bool:
    return "rate_limit" in _response_error_text(response).lower()


def _run_deep_research_request(client: OpenAI, prompt: str, settings: Any) -> Any:
    for attempt in range(len(RATE_LIMIT_RETRY_DELAYS_SECONDS) + 1):
        response = client.responses.create(
            model=settings.openai_deep_research_model,
            input=prompt,
            background=True,
            max_tool_calls=settings.openai_deep_research_max_tool_calls,
            tools=[{"type": "web_search_preview"}],
        )
        response = _wait_for_response(
            client=client,
            response=response,
            timeout_seconds=settings.openai_deep_research_timeout_seconds,
            poll_interval=settings.openai_deep_research_poll_interval_seconds,
        )
        status = getattr(response, "status", None)
        if status in (None, "completed"):
            return response
        if _is_rate_limit_response(response) and attempt < len(RATE_LIMIT_RETRY_DELAYS_SECONDS):
            delay = RATE_LIMIT_RETRY_DELAYS_SECONDS[attempt]
            logger.warning("OpenAI Deep Research rate-limited; retrying in %s seconds.", delay)
            time.sleep(delay)
            continue
        error = getattr(response, "error", None)
        raise RuntimeError(f"OpenAI Deep Research response ended with status={status}: {error}")

    raise RuntimeError("OpenAI Deep Research failed after retry attempts.")


def _article_content(item: Dict[str, Any]) -> str:
    key_points = item.get("key_points") or []
    if isinstance(key_points, list):
        key_points_text = "\n".join(f"- {str(point).strip()}" for point in key_points if str(point).strip())
    else:
        key_points_text = str(key_points).strip()

    parts = [
        f"Published date: {item.get('published_date', 'unknown')}",
        f"Source: {item.get('source', 'OpenAI Deep Research')}",
        f"Snippet: {item.get('snippet', '')}",
        f"Why it fits: {item.get('why_it_fits', '')}",
        f"Key points:\n{key_points_text}" if key_points_text else "",
        f"Deep research summary: {item.get('summary', '')}",
    ]
    return "\n\n".join(part for part in parts if part.strip())


def collect_articles_for_category(category: str, max_results: int = 6) -> List[Article]:
    """
    Collect category-matched articles with OpenAI Deep Research.

    The downstream Quality/Summarizer agents still run so the rest of the
    pipeline keeps the same behavior and output format.
    """
    settings = get_settings()
    requested_results = min(max_results, settings.openai_deep_research_max_results)
    if requested_results < max_results:
        logger.info(
            "Capping OpenAI Deep Research results from %s to %s.",
            max_results,
            requested_results,
        )
    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_deep_research_timeout_seconds,
    )
    prompt = _build_research_prompt(category=category, max_results=requested_results)

    logger.info(
        "Starting OpenAI Deep Research collection for %s with model=%s",
        category,
        settings.openai_deep_research_model,
    )
    response = _run_deep_research_request(
        client=client,
        prompt=prompt,
        settings=settings,
    )

    text = _extract_text(response)
    if not text:
        raise RuntimeError("OpenAI Deep Research returned no final text.")

    items = _parse_articles_json(text)
    now = datetime.now(APP_TIMEZONE).isoformat()
    articles: List[Article] = []
    seen_urls = set()

    for item in items:
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = str(item.get("title") or "(no title)").strip()
        snippet = str(item.get("snippet") or item.get("summary") or "").strip()
        source = str(item.get("source") or "OpenAI Deep Research").strip()
        articles.append(
            Article(
                id=str(uuid.uuid4()),
                category=category,
                title=title,
                url=url,
                snippet=snippet[:1000],
                content=_article_content(item),
                source=f"OpenAI Deep Research: {source}",
                collected_at=now,
            )
        )
        if len(articles) >= requested_results:
            break

    return articles
