from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .agent_logger import AgentLogger
from .config import APP_TIMEZONE
from .agents import (
    Article,
    ArticleEvaluation,
    ArticleSummary,
    article_to_dict,
    compose_newsletter_section,
    evaluate_article,
    standardize_newsletter,
    summarize_article,
    summary_to_dict,
)
from .config import get_settings
from .image_collector import collect_and_save_image
from .storage import save_run, save_newsletter_text


def _collect_both(category: str, max_results: int) -> List[Article]:
    """
    Run both Tavily and Deep Research for the category, merge and dedupe by URL.
    Returns combined list (Tavily first, then deep; duplicates by URL removed).
    """
    from . import agents
    from . import deep_research
    tavily_articles = agents.collect_articles_for_category(category=category, max_results=max_results)
    deep_articles = deep_research.collect_articles_for_category(category=category, max_results=max_results)
    seen_urls = set()
    merged: List[Article] = []
    for a in tavily_articles + deep_articles:
        u = (a.url or "").strip()
        if u and u not in seen_urls:
            seen_urls.add(u)
            merged.append(a)
    return merged


def _get_collector():
    """Return the article collector for the configured backend (tavily, deep, or both)."""
    from . import agents
    from . import deep_research
    settings = get_settings()
    if settings.collector_type == "deep":
        return deep_research.collect_articles_for_category
    if settings.collector_type == "both":
        return _collect_both
    return agents.collect_articles_for_category


def run_collection_pipeline(
    categories: List[str] | None = None,
    audience_description: str = "AI practitioners and leaders at a bank",
    max_results_per_category: int = 6,
    logger: Optional[AgentLogger] = None,
) -> Dict:
    """
    Full multi-agent pipeline for a single collection run:
    - Collector Agent: fetch articles per category (Tavily, Deep Research RSS, or both, per AI_DIGEST_COLLECTOR).
    - Quality Agent: accept/reject + score each article.
    - Summarizer Agent: summarize accepted articles.
    - Persist everything to data/. Logs each agent step if logger is provided.
    """
    settings = get_settings()
    if categories is None:
        categories = settings.default_categories

    collect_fn = _get_collector()
    run_id = datetime.now(APP_TIMEZONE).strftime("%Y%m%d-%H%M%S")
    run_started_at = datetime.now(APP_TIMEZONE).isoformat()
    own_logger = logger is None
    if own_logger:
        logger = AgentLogger(phase="collect", run_id=run_id, echo=True)

    all_articles: List[Article] = []
    all_evaluations: List[ArticleEvaluation] = []
    all_summaries: List[ArticleSummary] = []

    try:
        for category in categories:
            logger.step(
                "collector",
                "starting",
                f"Fetching articles for category '{category}' (max_results={max_results_per_category}, collector={settings.collector_type}).",
                details={"category": category, "max_results": max_results_per_category, "collector": settings.collector_type},
            )
            articles = collect_fn(
                category=category, max_results=max_results_per_category
            )
            all_articles.extend(articles)
            logger.step(
                "collector",
                "finished",
                f"Collected {len(articles)} articles for '{category}'.",
                details={"category": category, "count": len(articles)},
            )

            for article in articles:
                logger.step(
                    "quality",
                    "evaluating",
                    f"Article: {article.title[:60]}...",
                    details={"article_id": article.id, "url": article.url},
                )
                evaluation = evaluate_article(
                    article=article, audience_description=audience_description
                )
                all_evaluations.append(evaluation)
                logger.step(
                    "quality",
                    "decision",
                    f"Decision: {evaluation.decision}, score={evaluation.quality_score}. {evaluation.notes}",
                    details={
                        "article_id": article.id,
                        "decision": evaluation.decision,
                        "quality_score": evaluation.quality_score,
                        "flags": evaluation.flags,
                        "notes": evaluation.notes,
                    },
                )

                # For deep or both, use lower bar (>=2) so more feed-sourced articles get summarized
                quality_bar = 2 if settings.collector_type in ("deep", "both") else 3
                if evaluation.decision == "accept" and evaluation.quality_score >= quality_bar:
                    logger.step(
                        "summarizer",
                        "summarizing",
                        f"Article: {article.title[:60]}...",
                        details={"article_id": article.id},
                    )
                    summary = summarize_article(
                        article=article, audience_description=audience_description
                    )
                    all_summaries.append(summary)
                    logger.step(
                        "summarizer",
                        "finished",
                        f"Subject: {summary.suggested_subject}",
                        details={
                            "article_id": article.id,
                            "suggested_subject": summary.suggested_subject,
                            "summary_preview": summary.summary[:200] + "..." if len(summary.summary) > 200 else summary.summary,
                        },
                    )
    finally:
        if own_logger:
            logger.close()

    run_payload: Dict = {
        "run_id": run_id,
        "run_started_at": run_started_at,
        "categories": categories,
        "collector_type": settings.collector_type,
        "articles": [article_to_dict(a) for a in all_articles],
        "evaluations": [asdict(e) for e in all_evaluations],
        "summaries": [summary_to_dict(s) for s in all_summaries],
    }

    save_run(run_payload)
    return run_payload


def _index_by_article_id(
    evaluations: List[Dict], summaries: List[Dict]
) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    eval_by_id = {e["article_id"]: e for e in evaluations}
    summary_by_id = {s["article_id"]: s for s in summaries}
    return eval_by_id, summary_by_id


def _source_from_url(url: str) -> str:
    """Extract a short source label from URL (e.g. cnbc.com, reuters.com)."""
    if not url:
        return "—"
    try:
        netloc = urlparse(url).netloc or ""
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or "—"
    except Exception:
        return "—"


def _date_from_iso(iso_str: Optional[str]) -> str:
    """Format ISO date as 'Mon DD, YYYY' in UTC+8 for roundup header and table."""
    if not iso_str:
        return datetime.now(APP_TIMEZONE).strftime("%b %d, %Y")
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_local = dt.astimezone(APP_TIMEZONE)
        return dt_local.strftime("%b %d, %Y")
    except Exception:
        return datetime.now(APP_TIMEZONE).strftime("%b %d, %Y")


def _build_roundup_header(
    category: str,
    run_id: str,
    week_ending_date: Optional[str] = None,
    title_override: Optional[str] = None,
    intro_override: Optional[str] = None,
) -> str:
    """Build Copilot-style title and intro (e.g. 'AI News Roundup (Week Ending ...)')."""
    if week_ending_date is None and run_id:
        try:
            # run_id is like 20260208-153640 (in UTC+8)
            y, m, d = run_id[:4], run_id[4:6], run_id[6:8]
            week_ending_date = _date_from_iso(f"{y}-{m}-{d}T12:00:00+08:00")
        except Exception:
            week_ending_date = datetime.now(APP_TIMEZONE).strftime("%b %d, %Y")
    elif week_ending_date is None:
        week_ending_date = datetime.now(APP_TIMEZONE).strftime("%b %d, %Y")
    title = title_override or f"AI News Roundup (Week Ending {week_ending_date})"
    intro = intro_override or (
        "In the past week, the AI world witnessed record-breaking tech deals, "
        "cutting-edge product launches, market upheavals driven by AI breakthroughs, "
        "and pivotal regulatory moves. Below is a concise summary of the most impactful "
        "AI news, followed by detailed highlights:"
    )
    return f"# {title}\n\n{intro}\n\n"


def _build_roundup_table(
    selected_items: List[Tuple[Dict, Dict, Dict]],
    run_id: str,
) -> str:
    """Build a markdown table: Date | Headline | Source | Summary (Copilot-style)."""
    lines = [
        "## Key Events This Week\n",
        "| Date | Headline | Source | Summary |",
        "|------|----------|--------|---------|",
    ]
    for article, _eval, summary in selected_items:
        date = _date_from_iso(article.get("collected_at"))
        headline = (summary.get("suggested_subject") or article.get("title") or "(no title)").strip()
        source = _source_from_url(article.get("url", ""))
        summary_text = (summary.get("summary") or "").strip().replace("\n", " ")
        # Escape pipe in cells for markdown
        headline = headline.replace("|", "\\|")
        summary_text = summary_text.replace("|", "\\|")
        lines.append(f"| {date} | {headline} | {source} | {summary_text} |")
    return "\n".join(lines) + "\n"


def compose_newsletter_from_run(
    run_payload: Dict,
    category: str,
    audience: str,
    tone: str,
    max_items: int = 3,
    standardize: bool = True,
    target_max_words: int = 500,
    target_words_per_item: int = 40,
    output_format: str = "card",
    roundup_title: Optional[str] = None,
    roundup_intro: Optional[str] = None,
    logger: Optional[AgentLogger] = None,
) -> str:
    """
    Given a stored run and a category, compose a newsletter section.
    output_format: "card" (emoji headlines + summaries) or "table" (Date | Headline | Source | Summary).
    When format is "table", exactly max_items rows are output; no composer/standardizer.
    Logs each agent step if logger is provided.
    """
    run_id = run_payload.get("run_id", "")
    compose_run_id = f"{run_id}_{datetime.now(APP_TIMEZONE).strftime('%H%M%S')}"
    own_logger = logger is None
    if own_logger:
        logger = AgentLogger(phase="compose", run_id=compose_run_id, echo=True)

    articles: List[Dict] = run_payload.get("articles", [])
    evaluations: List[Dict] = run_payload.get("evaluations", [])
    summaries: List[Dict] = run_payload.get("summaries", [])

    eval_by_id, summary_by_id = _index_by_article_id(evaluations, summaries)

    # Filter articles by category and acceptance (lower quality bar for deep or both)
    quality_min = 2 if run_payload.get("collector_type") in ("deep", "both") else 3
    eligible_items = []
    for article in articles:
        if article.get("category") != category:
            continue
        evaluation = eval_by_id.get(article["id"])
        summary = summary_by_id.get(article["id"])
        if not evaluation or not summary:
            continue
        if evaluation.get("decision") != "accept" or int(
            evaluation.get("quality_score", 0)
        ) < quality_min:
            continue
        eligible_items.append((article, evaluation, summary))

    # Sort by quality score (desc) as a simple heuristic
    eligible_items.sort(
        key=lambda t: int(t[1].get("quality_score", 0)), reverse=True
    )
    selected_items = eligible_items[:max_items]

    if not selected_items:
        logger.step(
            "compose",
            "no_eligible",
            f"No eligible items for '{category}'. Writing fallback message.",
            details={"category": category},
        )
        header = _build_roundup_header(
            category=category,
            run_id=run_id,
            title_override=roundup_title,
            intro_override=roundup_intro,
        )
        fallback = (
            f"No articles passed quality for **{category}** this run.\n\n"
            "Try: (1) increase `--max-results` (e.g. 15) and re-run, "
            "(2) use a different category, or (3) run `collect` with more categories then `compose` for this one."
        )
        text = header + fallback
        if own_logger:
            logger.close()
        save_newsletter_text(text=text, category=category, run_id=run_id)
        return text
    # Use up to max_items; if we have fewer (e.g. 1 or 2), still compose with what we have
    if len(selected_items) < max_items:
        logger.step(
            "compose",
            "note",
            f"Only {len(selected_items)} eligible item(s) for '{category}' (requested {max_items}). Composing with {len(selected_items)} section(s).",
            details={"requested": max_items, "using": len(selected_items)},
        )

    # Copilot-style table format: fixed number of sections as Date | Headline | Source | Summary
    if output_format == "table":
        try:
            logger.step(
                "format",
                "building",
                f"Building table with exactly {len(selected_items)} sections (Date | Headline | Source | Summary).",
                details={"sections": len(selected_items)},
            )
            header = _build_roundup_header(
                category=category,
                run_id=run_id,
                title_override=roundup_title,
                intro_override=roundup_intro,
            )
            table = _build_roundup_table(selected_items, run_id)
            text = header + table
        finally:
            if own_logger:
                logger.close()
        save_newsletter_text(text=text, category=category, run_id=run_id)
        return text

    # Card format: collect one image per article, then composer + optional standardizer, then prepend roundup header
    composer_items: List[Dict[str, str]] = []
    for idx, (article, _evaluation, summary) in enumerate(selected_items, start=1):
        image_path: Optional[str] = None
        try:
            logger.step(
                "image_collector",
                "fetching",
                f"Article {idx}: {article.get('title', '')[:50]}...",
                details={"url": article.get("url", "")},
            )
            image_path = collect_and_save_image(
                article_url=article.get("url", ""),
                run_id=run_id,
                index=idx,
            )
            if image_path:
                logger.step("image_collector", "saved", f"Saved image for item {idx}: {image_path}", details={"path": image_path})
            else:
                logger.step("image_collector", "skipped", f"No image found for item {idx}", details={})
        except Exception as e:
            logger.step("image_collector", "error", f"Item {idx}: {e}", details={})
        composer_items.append(
            {
                "title": summary.get("suggested_subject")
                or article.get("title")
                or "(no title)",
                "url": article.get("url", ""),
                "summary": summary.get("summary", ""),
                "image_path": image_path or "",
            }
        )

    try:
        logger.step(
            "composer",
            "starting",
            f"Category={category}, audience={audience}, tone={tone}, sections={len(composer_items)}.",
            details={
                "category": category,
                "audience": audience,
                "tone": tone,
                "num_items": len(composer_items),
            },
        )
        text = compose_newsletter_section(
            category=category,
            audience=audience,
            tone=tone,
            items=composer_items,
        )
        logger.step(
            "composer",
            "finished",
            f"Draft length: {len(text)} chars, ~{len(text.split())} words.",
            details={"char_count": len(text), "word_count": len(text.split())},
        )

        if standardize:
            logger.step(
                "standardizer",
                "starting",
                f"Normalizing length (max {target_max_words} words) and structure.",
                details={
                    "target_max_words": target_max_words,
                    "target_words_per_item": target_words_per_item,
                },
            )
            text, std_details = standardize_newsletter(
                draft=text,
                category=category,
                audience=audience,
                target_max_words=target_max_words,
                target_words_per_item=target_words_per_item,
            )
            logger.step(
                "standardizer",
                "finished",
                f"Words: {std_details['word_count_before']} -> {std_details['word_count_after']}. "
                f"Changes: {std_details['changes_applied']}",
                details=std_details,
            )
    finally:
        if own_logger:
            logger.close()

    # Prepend Copilot-style roundup title and intro
    header = _build_roundup_header(
        category=category,
        run_id=run_id,
        title_override=roundup_title,
        intro_override=roundup_intro,
    )
    text = header + text

    save_newsletter_text(text=text, category=category, run_id=run_id)
    return text

