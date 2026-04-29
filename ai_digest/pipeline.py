from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
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
    generate_digest_headline,
    standardize_newsletter,
    summarize_article,
    summary_to_dict,
)
from .config import get_settings
from .image_collector import collect_and_save_image
from .formatter import render_newsletter_html
from .storage import save_run, save_newsletter_text, save_newsletter_html


def _collect_both(category: str, max_results: int) -> List[Article]:
    """
    Run both Tavily and Deep Research for the category, merge and dedupe by URL.
    Returns combined list (Tavily first, then deep; duplicates by URL removed).
    """
    from . import agents
    from . import deep_research
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_tavily = pool.submit(agents.collect_articles_for_category, category=category, max_results=max_results)
        f_deep = pool.submit(deep_research.collect_articles_for_category, category=category, max_results=max_results)
        tavily_articles = f_tavily.result()
        deep_articles = f_deep.result()
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



def _is_quota_exhausted(exc: Exception) -> bool:
    """Return True if the exception is an OpenAI insufficient_quota (billing) error."""
    msg = str(exc)
    return "insufficient_quota" in msg or (
        "429" in msg and "quota" in msg.lower()
    )


def run_collection_pipeline(
    categories: List[str] | None = None,
    audience_description: str = "AI practitioners and leaders at a bank",
    max_results_per_category: int = 6,
    logger: Optional[AgentLogger] = None,
    max_workers: int = 5,
    max_pool: Optional[int] = None,
) -> Dict:
    """
    Full multi-agent pipeline for a single collection run.

    Parallelism strategy (ThreadPoolExecutor — no async rewrites needed):
      - All articles within a category are evaluated by the Quality Agent concurrently.
      - All accepted articles are summarised concurrently across the whole category batch.
      - A semaphore (max_workers) caps simultaneous LLM calls to avoid rate-limit errors.
      - Collection itself stays sequential per category (Tavily is one call per category).
      - Thread-safe logging via a lock so log lines don't interleave.
    """
    settings = get_settings()
    if categories is None:
        categories = settings.default_categories

    collect_fn = _get_collector()
    quality_bar = 2 if settings.collector_type in ("deep", "both") else 3
    run_id = datetime.now(APP_TIMEZONE).strftime("%Y%m%d-%H%M%S")
    run_started_at = datetime.now(APP_TIMEZONE).isoformat()
    own_logger = logger is None
    if own_logger:
        logger = AgentLogger(phase="collect", run_id=run_id, echo=True)

    # Lock so parallel threads can call logger.step() without interleaving output
    log_lock = threading.Lock()

    def safe_log(agent, action, message, details=None):
        with log_lock:
            logger.step(agent, action, message, details=details)

    all_articles: List[Article] = []
    all_evaluations: List[ArticleEvaluation] = []
    all_summaries: List[ArticleSummary] = []

    def _evaluate_one(article: Article):
        """Run quality evaluation for one article. Returns (article, evaluation)."""
        safe_log("quality", "evaluating", f"Article: {article.title[:60]}...",
                 details={"article_id": article.id, "url": article.url})
        try:
            evaluation = evaluate_article(article=article, audience_description=audience_description)
            safe_log("quality", "decision",
                     f"Decision: {evaluation.decision}, score={evaluation.quality_score}. {evaluation.notes}",
                     details={
                         "article_id": article.id,
                         "decision": evaluation.decision,
                         "quality_score": evaluation.quality_score,
                         "flags": evaluation.flags,
                         "notes": evaluation.notes,
                     })
            return article, evaluation
        except Exception as exc:
            if _is_quota_exhausted(exc):
                raise  # propagate immediately — no point continuing
            safe_log("quality", "error", f"Article {article.id}: {exc}", details={"error": str(exc)})
            # Return a rejected evaluation so the article is safely skipped
            fallback = ArticleEvaluation(
                article_id=article.id, decision="reject", quality_score=0,
                flags=["evaluation_error"], notes=str(exc),
            )
            return article, fallback

    def _summarize_one(article: Article):
        """Summarise one accepted article. Returns (article, summary) or (article, None) on error."""
        safe_log("summarizer", "summarizing", f"Article: {article.title[:60]}...",
                 details={"article_id": article.id})
        try:
            summary = summarize_article(article=article, audience_description=audience_description)
            safe_log("summarizer", "finished", f"Subject: {summary.suggested_subject}",
                     details={
                         "article_id": article.id,
                         "suggested_subject": summary.suggested_subject,
                         "summary_preview": summary.summary[:200] + "..." if len(summary.summary) > 200 else summary.summary,
                     })
            return article, summary
        except Exception as exc:
            if _is_quota_exhausted(exc):
                raise  # propagate immediately — no point continuing
            safe_log("summarizer", "error", f"Article {article.id}: {exc}", details={"error": str(exc)})
            return article, None

    try:
        for category in categories:
            safe_log("collector", "starting",
                     f"Fetching articles for category '{category}' "
                     f"(max_results={max_results_per_category}, collector={settings.collector_type}).",
                     details={"category": category, "max_results": max_results_per_category,
                              "collector": settings.collector_type})

            # max_pool lets the user pass a larger pool to the evaluator than max_results.
            # Falls back to max_results_per_category if not set.
            pool_size = max_pool if max_pool is not None else max_results_per_category
            articles = collect_fn(category=category, max_results=pool_size)
            all_articles.extend(articles)

            safe_log("collector", "finished",
                     f"Collected {len(articles)} articles for '{category}'. "
                     f"Evaluating {len(articles)} articles in parallel (max_workers={max_workers}).",
                     details={"category": category, "count": len(articles)})

            # ── Phase 1: Parallel quality evaluation ──────────────────────────
            articles_to_summarise: List[Article] = []
            try:
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {pool.submit(_evaluate_one, art): art for art in articles}
                    for future in as_completed(futures):
                        art, evaluation = future.result()
                        all_evaluations.append(evaluation)
                        if evaluation.decision == "accept" and evaluation.quality_score >= quality_bar:
                            articles_to_summarise.append(art)
            except Exception as exc:
                if _is_quota_exhausted(exc):
                    safe_log("pipeline", "quota_error",
                             "OpenAI quota exhausted — stopping pipeline. "
                             "Top up your credits at platform.openai.com/settings/billing.",
                             details={"error": str(exc)})
                    raise RuntimeError(
                        "OpenAI quota exhausted. Please add credits at "
                        "platform.openai.com/settings/billing and re-run."
                    ) from exc
                raise

            safe_log("quality", "batch_done",
                     f"Evaluation complete for '{category}': "
                     f"{len(articles_to_summarise)}/{len(articles)} passed quality bar.",
                     details={"accepted": len(articles_to_summarise), "total": len(articles)})

            if not articles_to_summarise:
                continue

            # ── Phase 2: Parallel summarisation ───────────────────────────────
            try:
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {pool.submit(_summarize_one, art): art for art in articles_to_summarise}
                    for future in as_completed(futures):
                        art, summary = future.result()
                        if summary is not None:
                            all_summaries.append(summary)
            except Exception as exc:
                if _is_quota_exhausted(exc):
                    safe_log("pipeline", "quota_error",
                             "OpenAI quota exhausted — stopping pipeline. "
                             "Top up your credits at platform.openai.com/settings/billing.",
                             details={"error": str(exc)})
                    raise RuntimeError(
                        "OpenAI quota exhausted. Please add credits at "
                        "platform.openai.com/settings/billing and re-run."
                    ) from exc
                raise

            safe_log("summarizer", "batch_done",
                     f"Summarisation complete for '{category}': {len(all_summaries)} summaries so far.",
                     details={"summaries": len(all_summaries)})

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


# Research categories where every article is intentionally from the same domain.
_RESEARCH_CATEGORIES = {"ai_research", "ai_research_arxiv"}

# Stop words stripped before text fingerprinting.
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "that", "this", "its", "it", "as", "new", "now",
    "how", "why", "what", "will", "can", "could", "may", "just", "more",
    "using", "via", "into", "over", "about", "based", "toward", "towards",
    "said", "says", "also", "still", "even", "than", "then", "when", "where",
}


def _text_fingerprint(text: str) -> frozenset:
    """Meaningful lowercase word set from a block of text, stop words removed."""
    import re
    words = re.sub(r"[^a-z0-9 ]", "", text.lower()).split()
    return frozenset(w for w in words if w not in _STOP_WORDS and len(w) > 2)


def _entity_fingerprint(text: str) -> frozenset:
    """
    Extract named entities from original-case text:
    - Single capitalised tokens (proper nouns: Anthropic, Mythos, GPT)
    - Consecutive capitalised bigrams joined with _ (Claude_Mythos, GPT_5)
    These are the most reliable duplicate signal because every article covering
    the same story uses the same company/product/person names regardless of angle.
    """
    import re
    tokens = re.findall(r'\b[A-Z][a-zA-Z0-9]+\b', text)
    entities = {t.lower() for t in tokens if len(t) > 2}
    bigrams = re.findall(r'\b([A-Z][a-zA-Z0-9]+)\s+([A-Z][a-zA-Z0-9]+)\b', text)
    for a, b in bigrams:
        entities.add(f"{a.lower()}_{b.lower()}")
    return frozenset(entities)


def _article_text(article: Dict, summary: Dict) -> str:
    """Combine title and summary into one text blob for fingerprinting."""
    title = summary.get("suggested_subject") or article.get("title") or ""
    summary_text = summary.get("summary") or ""
    return f"{title} {summary_text}"


def _is_same_story(
    text_a: str,
    text_b: str,
    entity_threshold: float = 0.45,
    text_threshold: float = 0.38,
) -> bool:
    """
    Return True if two articles are covering the same underlying story.

    Two independent signals — either one firing means duplicate:

    1. Named entity overlap >= entity_threshold (default 0.55):
       Catches "Anthropic rogue AI shocks researchers" vs "Anthropic Mythos sparks
       cyber fears" — both mention Anthropic + Mythos regardless of angle.
       This is the primary signal for breaking news covered from multiple angles.

    2. Combined text overlap >= text_threshold (default 0.38):
       Catches near-identical articles or very similar rewrites where entity
       extraction alone might miss something.
    """
    # Signal 1: named entity overlap
    ents_a = _entity_fingerprint(text_a)
    ents_b = _entity_fingerprint(text_b)
    if ents_a and ents_b:
        entity_overlap = len(ents_a & ents_b) / min(len(ents_a), len(ents_b))
        if entity_overlap >= entity_threshold:
            return True

    # Signal 2: combined text overlap
    fp_a = _text_fingerprint(text_a)
    fp_b = _text_fingerprint(text_b)
    if fp_a and fp_b:
        text_overlap = len(fp_a & fp_b) / min(len(fp_a), len(fp_b))
        if text_overlap >= text_threshold:
            return True

    return False


def _deduplicate_by_story(
    items: List[Tuple[Dict, Dict, Dict]],
    category: str = "",
) -> List[Tuple[Dict, Dict, Dict]]:
    """
    Remove articles covering the same underlying story, keeping the highest-scoring one.
    Items must already be sorted by quality score descending so the best version is kept.

    Uses two signals: named entity overlap (primary) + text similarity (secondary).
    Research categories use only text similarity since entity names like 'arxiv'
    appear in every paper and would cause false positives.
    """
    is_research = category in _RESEARCH_CATEGORIES
    seen_texts: List[str] = []
    deduped = []

    for article, evaluation, summary in items:
        text = _article_text(article, summary)

        is_duplicate = False
        for seen_text in seen_texts:
            if is_research:
                # For research: text similarity only — entity names overlap too much
                fp = _text_fingerprint(text)
                seen_fp = _text_fingerprint(seen_text)
                if fp and seen_fp:
                    overlap = len(fp & seen_fp) / min(len(fp), len(seen_fp))
                    if overlap >= 0.38:
                        is_duplicate = True
                        break
            else:
                if _is_same_story(text, seen_text):
                    is_duplicate = True
                    break

        if is_duplicate:
            continue

        seen_texts.append(text)
        deduped.append((article, evaluation, summary))

    return deduped


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
    """Build header title and intro (e.g. 'AI Digest (March 9, 2026)')."""
    if week_ending_date is None and run_id:
        try:
            # run_id is like 20260208-153640 (in UTC+8)
            y, m, d = run_id[:4], run_id[4:6], run_id[6:8]
            week_ending_date = _date_from_iso(f"{y}-{m}-{d}T12:00:00+08:00")
        except Exception:
            week_ending_date = datetime.now(APP_TIMEZONE).strftime("%b %d, %Y")
    elif week_ending_date is None:
        week_ending_date = datetime.now(APP_TIMEZONE).strftime("%b %d, %Y")
    title = title_override or f"AI Digest ({week_ending_date})"
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
    target_words_per_item: int = 80,
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

    # Sort by quality score (desc) so dedup always keeps the best version of each story
    eligible_items.sort(
        key=lambda t: int(t[1].get("quality_score", 0)), reverse=True
    )

    # Deduplicate by story — remove articles covering the same event from different sources
    deduplicated_items = _deduplicate_by_story(eligible_items, category=category)
    selected_items = deduplicated_items[:max_items]

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
    logger.step(
        "image_collector",
        "fetching",
        f"Fetching {len(selected_items)} image(s) in parallel...",
        details={"count": len(selected_items)},
    )

    def _fetch_image(idx: int, article: Dict) -> Tuple[int, Optional[str]]:
        try:
            return idx, collect_and_save_image(
                article_url=article.get("url", ""),
                run_id=run_id,
                index=idx,
            )
        except Exception as exc:
            return idx, None

    image_paths: Dict[int, Optional[str]] = {}
    with ThreadPoolExecutor(max_workers=min(len(selected_items), 5)) as pool:
        img_futures = [
            pool.submit(_fetch_image, idx, article)
            for idx, (article, _evaluation, _summary) in enumerate(selected_items, start=1)
        ]
        for future in as_completed(img_futures):
            idx, image_path = future.result()
            image_paths[idx] = image_path
            if image_path:
                logger.step("image_collector", "saved", f"Saved image for item {idx}: {image_path}", details={"path": image_path})
            else:
                logger.step("image_collector", "skipped", f"No image found for item {idx}", details={})

    composer_items: List[Dict[str, str]] = []
    for idx, (article, _evaluation, summary) in enumerate(selected_items, start=1):
        composer_items.append(
            {
                "title": summary.get("suggested_subject")
                or article.get("title")
                or "(no title)",
                "url": article.get("url", ""),
                "summary": summary.get("summary", ""),
                "image_path": image_paths.get(idx) or "",
                "technical_specs": summary.get("technical_specs", ""),
                "industry_impact": summary.get("industry_impact", ""),
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

    # Generate a single teaser headline from the final items
    digest_headline = generate_digest_headline(composer_items)

    # Render and save self-contained HTML newsletter
    html = render_newsletter_html(
        items=composer_items,
        title=roundup_title or f"AI Digest ({_date_from_iso(run_id[:8] + 'T12:00:00+08:00' if len(run_id) >= 8 else None)})",
        section_label=category.replace("_", " ").title(),
        intro=roundup_intro,
        digest_headline=digest_headline,
    )
    save_newsletter_html(html=html, category=category, run_id=run_id)

    return text