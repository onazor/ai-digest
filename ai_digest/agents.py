from __future__ import annotations

import textwrap
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime

from typing import Any, Dict, List, Optional

from tavily import TavilyClient  # type: ignore[import-error]

from .config import APP_TIMEZONE, get_settings
from .llm import chat_completion_json, chat_completion


settings = get_settings()
tavily_client = TavilyClient(api_key=settings.tavily_api_key) # type: ignore[reportUnknownMemberType]


@dataclass
class Article:
    id: str
    category: str
    title: str
    url: str
    snippet: str
    content: str
    source: str
    collected_at: str


@dataclass
class ArticleEvaluation:
    article_id: str
    decision: str  # "accept" or "reject"
    quality_score: int  # 1–5
    flags: List[str]
    notes: str


@dataclass
class ArticleSummary:
    article_id: str
    summary: str
    key_points: List[str]  # kept for backward compatibility
    suggested_subject: str
    why_this_matters: str = ""  # paragraph form, aligned with bank/audience


def collect_articles_for_category(
    category: str,
    max_results: int = 6,
) -> List[Article]:
    """
    Collector Agent:
    Use Tavily to fetch recent, relevant items for a given category.
    """
    if category == "ai_technology":
        query = (
            "Latest AI and generative AI news from major tech companies in the last 7 days: "
            "Google, Apple, Microsoft, OpenAI, Meta, Amazon, NVIDIA, and similar. "
            "Product launches, announcements, and AI initiatives. Prioritize high-quality sources."
        )
    elif category == "ai_innovations":
        query = (
            "Latest AI and ML innovations in the last 7 days: new models, new methods, algorithms, "
            "research breakthroughs, technical advances. Focus on the technology itself: model releases, "
            "novel architectures, training techniques, inference improvements, and new AI/ML processes. "
            "Prioritize high-quality technical sources."
        )
    elif category == "ai_research":
        query = (
            "Latest AI/ML research in the last 7 days: new models, algorithms, technical techniques, "
            "research papers, architectures, training methods, optimization, benchmarks. "
            "Highly technical content for data scientists and AI researchers: arXiv, conference papers, "
            "model cards, ablation studies, novel methods. Prioritize research-oriented and technical sources."
        )
    else:
        query = (
            f"Latest important, non-duplicate news and resources in the last 7 days about "
            f"{category} related to AI and generative AI. Prioritize high-quality sources."
        )

    result = tavily_client.search(
        query=query,
        search_depth="advanced",
        max_results=max_results,
        include_raw_content=True,
    )

    articles: List[Article] = []
    now = datetime.now(APP_TIMEZONE).isoformat()

    for item in result.get("results", []):
        content = item.get("raw_content") or item.get("content") or ""
        snippet = (content or item.get("content") or "")[:1000]

        articles.append(
            Article(
                id=str(uuid.uuid4()),
                category=category,
                title=item.get("title") or "(no title)",
                url=item.get("url") or "",
                snippet=snippet,
                content=content,
                source="tavily",
                collected_at=now,
            )
        )

    return articles


def evaluate_article(
    article: Article,
    audience_description: str = "AI practitioners and leaders at a bank",
) -> ArticleEvaluation:
    """
    Quality Agent:
    Ask the LLM to determine whether this article is worth including, prioritizing trending and highly relevant news.
    """
    # When articles come from RSS/Atom (deep research), favor timely + trending / high-attention.
    from_rss = article.source and article.source.lower() != "tavily"
    rss_guidance = ""
    if from_rss:
        rss_guidance = (
            " This item is from curated RSS/Atom feeds (TechCrunch, VentureBeat, arXiv, etc.). "
            "Prioritize RELEVANT, TIMELY, and LIKELY TRENDING news: give quality_score 4 or 5 to stories that sound like they are (or would be) getting a lot of attention—e.g. major product launches, big company announcements, breakthrough research, widely discussed topics, record deals, regulatory milestones. "
            "Give 3 for clearly on-topic AI/tech news that is useful but not necessarily 'trending'. "
            "Use 'reject' or low scores only for off-topic, niche-without-impact, or clearly outdated content. Short snippets are normal for feeds; do not reject for that."
        )

    category_guidance = ""
    if article.category == "ai_innovations":
        category_guidance = (
            " For category ai_innovations: accept content about new models, methods, algorithms, "
            "research breakthroughs, and technical advances even if niche or from research feeds (e.g. arXiv, ML blogs). "
            "Technical relevance counts as high relevance."
        )
    elif article.category == "ai_technology":
        category_guidance = (
            " For category ai_technology: accept news from major tech companies (Google, Apple, Microsoft, etc.) "
            "about products, launches, and AI initiatives."
        )
    elif article.category == "ai_trends":
        category_guidance = (
            " For category ai_trends: accept any clearly AI/GenAI-related news, trends, or market developments."
        )
    elif article.category == "genai_tips":
        category_guidance = (
            " For category genai_tips: accept how-tos, tips, guides, and practical GenAI content."
        )
    elif article.category == "tools_updates":
        category_guidance = (
            " For category tools_updates: accept product releases, API updates, and software/tool announcements related to AI."
        )
    elif article.category == "policy_ethics":
        category_guidance = (
            " For category policy_ethics: accept policy, regulation, ethics, and governance news related to AI."
        )
    elif article.category == "ai_research":
        category_guidance = (
            " For category ai_research (research-focused, for data scientists / AI researchers): accept highly technical "
            "content on models, algorithms, research approaches, architectures, training techniques, benchmarks, "
            "novel methods, papers, and technical breakthroughs. Prefer research papers, model cards, method descriptions, "
            "and technical deep-dives. Reject purely product/marketing or non-technical content."
        )

    system_prompt = textwrap.dedent(
        f"""
        You are a quality-control editor for an internal AI newsletter focused on RELEVANT, TIMELY, and TRENDING AI/GenAI news.

        Your job:
        - Decide if a candidate article is suitable for inclusion.
        - PRIORITIZE: news that is timely, relevant, and likely getting a lot of attention (trending)—e.g. major announcements, big launches, breakthrough research, significant market or policy moves, widely discussed topics. Prefer stories that would be shared and talked about.{rss_guidance}{category_guidance}
        - Rate on a 1-5 scale: 5 = highly relevant + likely trending/high-attention; 4 = strong, timely, relevant; 3 = acceptable and on-topic; 1-2 = niche, outdated, or low relevance.
        - Flag issues (clickbait, low credibility, off-topic, outdated). For known outlets, lean toward accept when the story sounds timely and relevant; use higher scores (4-5) when it sounds like trending or high-impact news.

        Output strict JSON with the following shape:
        {{
          "decision": "accept" or "reject",
          "quality_score": integer 1-5,
          "flags": [string, ...],
          "notes": "short explanation"
        }}
        """
    ).strip()

    content_for_eval = (article.content or article.snippet or "")[:4000]
    user_prompt = textwrap.dedent(
        f"""
        Audience description: {audience_description}

        Category: {article.category}

        Title: {article.title}
        URL: {article.url}

        Snippet/content:
        ---
        {content_for_eval}
        ---

        Evaluate this item for inclusion in an internal AI newsletter.
        """
    ).strip()

    data = chat_completion_json(system_prompt=system_prompt, user_prompt=user_prompt)

    decision = str(data.get("decision", "reject")).lower()
    quality_score = int(data.get("quality_score", 1))
    flags = [str(f) for f in data.get("flags", [])]
    notes = str(data.get("notes", "")).strip()

    return ArticleEvaluation(
        article_id=article.id,
        decision=decision,
        quality_score=quality_score,
        flags=flags,
        notes=notes,
    )


def summarize_article(
    article: Article,
    audience_description: str = "AI practitioners and leaders at a bank",
) -> ArticleSummary:
    """
    Summarizer Agent:
    Create a concise summary (exactly 2 sentences) with an eye-catching headline for a single accepted item.
    """
    system_prompt = textwrap.dedent(
        """
        You are a newsletter writer for an internal AI/GenAI digest at a bank.

        Given a single article, produce:

        1. suggested_subject: An eye-catching, attention-grabbing headline. Use emojis if appropriate
           (e.g., 🚀 for launches, 🤖 for AI tools, 🌐 for global/tech, 💼 for business). Make it
           bold and engaging while staying professional. Focus on the most impactful aspect of the news.

        2. summary: A concise summary (exactly 2 sentences, no more). Focus on the key facts: what happened,
           who/what is involved, and the most important detail (e.g., numbers, impact, significance).
           Remove fluff and unnecessary details. Keep it tight and factual.

        3. key_points: Optional list of 2-3 short bullet strings (for backward compatibility).

        Prioritize: Capture only the most relevant and trending aspects. Focus on high-impact stories
        that matter to a bank audience.

        Output strict JSON with:
        {
          "suggested_subject": "eye-catching headline with emoji if appropriate",
          "summary": "exactly 2 sentences, key facts only",
          "key_points": ["...", "..."]
        }
        """
    ).strip()

    content_preview = article.content[:6000] or article.snippet

    user_prompt = textwrap.dedent(
        f"""
        Audience description: {audience_description}

        Category (keep content focused on this topic): {article.category}
        Title: {article.title}
        URL: {article.url}

        Content (may be truncated):
        ---
        {content_preview}
        ---
        """
    ).strip()

    data = chat_completion_json(system_prompt=system_prompt, user_prompt=user_prompt)

    summary = str(data.get("summary", "")).strip()
    key_points = [str(p) for p in data.get("key_points", [])]
    suggested_subject = str(data.get("suggested_subject", "")).strip()

    return ArticleSummary(
        article_id=article.id,
        summary=summary,
        key_points=key_points,
        suggested_subject=suggested_subject,
        why_this_matters="",  # No longer used, kept for backward compatibility
    )


def compose_newsletter_section(
    category: str,
    audience: str,
    tone: str,
    items: List[Dict[str, str]],
) -> str:
    """
    Composer Agent:
    Given a list of summarized items, draft a newsletter section with eye-catching headlines and concise content.

    `items` is a list of dicts with keys:
      - title (headline), url, summary (exactly 2 sentences), image_path (optional, for embedding)
    """
    system_prompt = textwrap.dedent(
        """
        You draft an internal AI/GenAI newsletter section for a bank.

        Format rules:
        - Keep content SHORT and attention-grabbing. Each news item must be exactly 2 sentences (no more).
        - Use the provided headline exactly as-is (it's already eye-catching with emojis if appropriate).
        - Focus on key facts: what happened, who/what is involved, and the most important detail.
        - Remove fluff and unnecessary details. Prioritize high-impact, trending, and relevant news.
        - If an image_path is provided for an item, add a single line after the 2 sentences and before "Read more": ![Headline](image_path) using the exact image_path given (e.g. images/run_id/1.jpg). This embeds the image for email.
        - End each item with a clear "Read more: <URL>" or "See more: <URL>" link.
        - Assume the content will be sent via email or pasted into a poster. Use simple markdown-style formatting (bold for headlines, plain text otherwise). No HTML.
        - Match the requested tone.

        Structure (plain text, markdown-friendly):
        - One short section heading that reflects the category/topic.
        - A brief 1-2 sentence intro that frames the section (optional, keep it concise).
        - For each item:
          - **Bold headline** (use the provided suggested_subject/title exactly as-is).
          - Exactly 2 sentences of content (use the provided summary; keep it tight and factual).
          - If image_path is provided: a line ![Headline](image_path) with the exact path.
          - "Read more: <URL>" or "See more: <URL>" on its own line.

        Example (with image):
        **🚀 Historic Tech Merger**
        SpaceX acquires xAI in an all-stock deal valuing the combined company at $1.25 trillion, the largest merger ever. Elon Musk's aim: build orbital AI data centers and unify AI with space ventures.
        ![Historic Tech Merger](images/20260208-153640/1.jpg)
        Read more: <URL>
        """
    ).strip()

    items_text_parts: List[str] = []
    for idx, item in enumerate(items, start=1):
        image_path = item.get("image_path", "").strip()
        img_line = f"\nImage path (embed as ![Headline](image_path) if present): {image_path}" if image_path else ""
        items_text_parts.append(
            textwrap.dedent(
                f"""
                Item {idx}
                Headline: {item.get("title", "")}
                URL: {item.get("url", "")}

                Summary (use exactly as-is, exactly 2 sentences):
                {item.get("summary", "")}
                {img_line}
                """
            ).strip()
        )

    items_block = "\n\n".join(items_text_parts)

    user_prompt = textwrap.dedent(
        f"""
        Audience: {audience}
        Tone: {tone}
        Category (keep the entire section focused on this topic): {category}

        Curated items to cover (prioritize high-impact, trending, and relevant news):

        {items_block}

        Draft the newsletter section. Use the exact headlines provided. Keep each item to exactly 2 sentences of content. For any item that has an image path, add a line ![Headline](image_path) after the 2 sentences (use the exact path given). End each item with "Read more: <URL>" or "See more: <URL>". Focus on key facts and remove fluff.
        """
    ).strip()

    return chat_completion(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.4)


def standardize_newsletter(
    draft: str,
    category: str,
    audience: str,
    target_max_words: int = 600,
    target_words_per_item: int = 120,
) -> tuple[str, Dict[str, Any]]:
    """
    Standardizer Agent:
    Normalize newsletter length and structure so every issue feels consistent.
    Returns (standardized_text, details_dict) for logging (e.g. word counts, changes_applied).
    """
    word_count_before = len(draft.split())
    system_prompt = textwrap.dedent(
        """
        You are an editor for an internal AI/GenAI newsletter. Your job is to standardize
        draft content so that every issue has the same structure and length guidelines.

        Rules:
        1. Structure: Use exactly this layout every time:
           - One main section heading (short, clear, on-topic).
           - A brief 1-2 sentence intro (optional, keep it concise).
           - For each item:
             - **Bold headline** (keep the eye-catching headline as-is, including emojis if present).
             - Exactly 2 sentences of content (keep it tight and factual; focus on key facts only).
             - "Read more: <URL>" or "See more: <URL>" on its own line.
        2. Length: Keep the total section under the requested max words. Each item must be
           exactly 2 sentences. Remove any fluff or unnecessary details. Prioritize
           key facts and high-impact information.
        3. Tone and focus: Preserve the original tone and audience. Keep all content focused
           on the topic. Do not add new information; only trim or rephrase for clarity and consistency.
           Ensure headlines remain eye-catching and attention-grabbing.
        4. Images: Preserve any markdown image lines in the form ![alt](path) exactly; do not remove or change them.

        You must respond with a single JSON object with these exact keys:
        - "standardized_text": string, the full standardized newsletter section (plain text, markdown-friendly).
        - "word_count_after": integer, word count of standardized_text.
        - "changes_applied": array of strings, short descriptions of what you changed.
        """
    ).strip()

    user_prompt = textwrap.dedent(
        f"""
        Audience: {audience}
        Category: {category}
        Target max total words: {target_max_words}
        Target words per item (approx): {target_words_per_item}

        Draft to standardize (word count: {word_count_before}):
        ---
        {draft}
        ---

        Output only valid JSON with keys: standardized_text, word_count_after, changes_applied.
        """
    ).strip()

    try:
        data = chat_completion_json(
            system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.2
        )
        standardized_text = str(data.get("standardized_text", draft)).strip()
        details: Dict[str, Any] = {
            "word_count_before": word_count_before,
            "word_count_after": int(data.get("word_count_after", len(standardized_text.split()))),
            "changes_applied": [str(x) for x in data.get("changes_applied", [])],
        }
    except Exception:
        standardized_text = draft
        details = {
            "word_count_before": word_count_before,
            "word_count_after": word_count_before,
            "changes_applied": ["Standardization skipped (LLM response parse failed)"],
        }
    return standardized_text, details


def article_to_dict(article: Article) -> Dict:
    return asdict(article)


def evaluation_to_dict(evaluation: ArticleEvaluation) -> Dict:
    return asdict(evaluation)


def summary_to_dict(summary: ArticleSummary) -> Dict:
    return asdict(summary)

