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
    suggested_subject: str


def collect_articles_for_category(
    category: str,
    max_results: int = 6,
) -> List[Article]:
    """
    Collector Agent:
    Use Tavily to fetch recent, relevant items for a given category.
    """
    if category == "ai_innovations":
        query = (
            "What is new and capable in AI in the last 7 days. "
            "Include: new model releases and what they can do (GPT, Gemini, Claude, Llama, Mistral, "
            "and similar) with benchmark results and capability comparisons; capability breakthroughs "
            "in reasoning, multimodality, long-context, or agents; open-source model or framework "
            "milestones that change what practitioners can build; and techniques crossing from research "
            "into real-world use such as new inference methods, quantization, or fine-tuning approaches. "
            "Also include: major AI product launches and initiatives from Google, Microsoft, OpenAI, "
            "Meta, Apple, Amazon, NVIDIA, and similar — focusing on the capability angle, not just the "
            "announcement. Exclude: market analysis, adoption trends, tips and tutorials, "
            "and academic papers without a release or deployment angle."
        )
    elif category == "ai_research":
        query = (
            "site:arxiv.org OR site:paperswithcode.com new AI ML research papers preprints last 7 days. "
            "New algorithms, novel architectures, SOTA benchmarks, groundbreaking results. "
            "Include: arXiv preprints, NeurIPS ICML ICLR papers, technical research results. "
            "Exclude: product launches, company news, how-to guides, opinion pieces."
        )
    elif category == "ai_research_arxiv":
        query = (
            "site:arxiv.org new AI ML research papers preprints last 7 days. "
            "New algorithms, novel architectures, SOTA benchmarks, groundbreaking results. "
            "Only arXiv preprints — no blogs, no news sites, no company announcements."
        )
    elif category == "genai_tips":
        query = (
            "Practical GenAI and LLM techniques for data scientists and AI practitioners last 7 days. "
            "Include: advanced prompting techniques (chain-of-thought, few-shot, structured outputs, "
            "system prompt design, prompt chaining), new tools for working with LLMs (agent frameworks, "
            "RAG tooling, evaluation libraries, IDE integrations, API features), and practical workflows "
            "using GenAI in real pipelines (LLMs for data analysis, building agents, prompt-to-code). "
            "Exclude: beginner ChatGPT guides, generic AI opinion pieces, product announcements "
            "without practical usage guidance, and listicles with no technical depth."
        )
    elif category == "ai_trends":
        query = (
            "AI and generative AI trends gaining widespread attention in the last 7 days. "
            "Include: industry adoption shifts, enterprise AI rollouts, AI market movements, "
            "widely debated AI topics, emerging use cases getting traction, surveys and reports "
            "on how organisations are using AI, and stories that many people in tech are discussing. "
            "Exclude: single product launches, individual research papers, how-to guides, "
            "company earnings, or one-off announcements without a broader trend angle. "
            "Prioritize stories from analysts, industry publications, and business press."
        )
    elif category == "ai_capability":
        query = (
            "AI capabilities and what AI can do now in the last 7 days. "
            "Include: knowledge assist and enterprise search powered by AI, voice AI and speech "
            "recognition advances, intelligent document processing and OCR, image and video "
            "generation (text-to-image, text-to-video), code generation and AI coding assistants, "
            "AI-powered translation and summarization, recommendation systems, predictive analytics, "
            "autonomous agents and robotics, and any new demonstration of what AI systems can accomplish. "
            "Focus on concrete capabilities — what the AI can DO — not market trends or research theory. "
            "Exclude: pure research papers, market analysis without capability details, opinion pieces."
        )
    else:
        query = (
            f"Latest important, non-duplicate news and resources in the last 7 days about "
            f"{category} related to AI and generative AI. Prioritize high-quality sources."
        )

    # Tavily enforces a hard 400-character query limit.
    query = query[:400]

    if category in ("ai_research", "ai_research_arxiv"):
        search_params: Dict[str, Any] = {
            "search_depth": "basic",
            "topic": "news",  # news topic favours recent publications over evergreen content
        }
        if category == "ai_research_arxiv":
            search_params["include_domains"] = ["arxiv.org"]
    elif category == "ai_innovations":
        search_params = {
            "search_depth": "basic",
            "topic": "news",  # news surfaces recent model releases and capability announcements
            "exclude_domains": ["arxiv.org"],
        }
    elif category == "genai_tips":
        search_params = {
            "search_depth": "basic",
            "topic": "general",
            "exclude_domains": ["arxiv.org"],
            # general topic (not news) — practical technique articles aren't always breaking news
        }
    elif category == "ai_trends":
        search_params = {
            "search_depth": "basic",
            "topic": "news",  # news topic surfaces recent widely-covered stories over evergreen content
            "exclude_domains": ["arxiv.org"],
        }
    elif category == "ai_capability":
        search_params = {
            "search_depth": "basic",
            "topic": "general",  # general topic catches both news and capability showcases
            "exclude_domains": ["arxiv.org"],
        }
    else:
        search_params = {
            "search_depth": "basic",
            "topic": "general",
            "exclude_domains": ["arxiv.org"],
        }

    result = tavily_client.search(
        query=query,
        max_results=max_results,
        include_raw_content=True,
        **search_params,
    )

    articles: List[Article] = []
    now = datetime.now(APP_TIMEZONE).isoformat()

    for item in result.get("results", []):
        content = item.get("raw_content") or item.get("content") or ""
        snippet = content[:1000]

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
            " For category ai_innovations: accept content that answers 'what is new and capable in AI'. "
            "Two equal pillars — (1) CAPABILITY: new model releases with benchmark results or capability "
            "comparisons, breakthroughs in reasoning/multimodality/agents/long-context, open-source "
            "milestones that change what practitioners can build, and techniques crossing from research "
            "into real use (inference, quantization, fine-tuning). (2) INDUSTRY: major AI product launches "
            "and initiatives from Google, Microsoft, OpenAI, Meta, Apple, Amazon, NVIDIA — focus on "
            "what the product can DO, not just that it was announced. "
            "Score 4-5 for clear capability advances or major releases with concrete details. "
            "Score 3 for solid product news or technical updates with real substance. "
            "REJECT: market analysis and adoption trends (use ai_trends), tips and tutorials "
            "(use genai_tips), pure academic papers without a release angle (use ai_research), "
            "and company announcements with no technical detail or capability discussion."
        )
    elif article.category == "ai_trends":
        category_guidance = (
            " For category ai_trends: accept ONLY stories that reflect a genuine trend — "
            "something that is gaining traction, being widely adopted, heavily debated, or shifting "
            "how the industry thinks about AI. Strong signals: adoption numbers, industry surveys, "
            "enterprise rollouts, market analysis, emerging use cases with real examples, topics "
            "that many outlets are covering simultaneously. "
            "Score 4-5 for stories backed by data, multiple organisations, or clear industry momentum. "
            "Score 3 for clearly trend-adjacent stories with a credible angle. "
            "REJECT: single product launches or announcements without a trend angle (use ai_innovations), "
            "individual research papers (use ai_research), how-to guides (use genai_tips), "
            "opinion pieces with no supporting evidence, or any story that is only about one company "
            "doing one thing with no broader pattern."
        )
    elif article.category == "genai_tips":
        category_guidance = (
            " For category genai_tips: the audience is data scientists and AI practitioners — "
            "accept ONLY content with genuine technical depth and practical value. "
            "Strong accepts: advanced prompting techniques (chain-of-thought, few-shot, structured outputs, "
            "prompt chaining, system prompt design), practical LLM tooling guides (RAG frameworks, "
            "agent libraries, evaluation tools, API features), and real workflow tutorials "
            "(LLMs for data analysis, building agents, integrating GenAI into pipelines). "
            "Score 4-5 for content a working data scientist could apply immediately. "
            "Score 3 for solid practitioner content that is useful but not immediately actionable. "
            "REJECT: beginner-level or consumer-facing guides ('10 ChatGPT prompts for productivity'), "
            "generic AI opinion pieces, product announcements without practical usage guidance, "
            "shallow listicles with no technical substance, and anything that assumes no prior AI knowledge."
        )
    elif article.category == "ai_research":
        category_guidance = (
            " For category ai_research: accept ONLY research-focused content—publications, technical papers, and "
            "journal/preprint-style articles (e.g. from arXiv, conferences, journals). Prefer: new algorithms, "
            "new technical trends in AI, groundbreaking results, novel methods, benchmarks, and formal research. "
            "REJECT: product launches, company announcements, general tech news, how-tos, or any non-publication content. "
            "When the source is arXiv or a research venue, lean accept; when it is a general news site, accept only if the article is clearly about a specific paper or research result."
        )
    elif article.category == "ai_research_arxiv":
        category_guidance = (
            " For category ai_research_arxiv: accept ONLY papers from arxiv.org. "
            "REJECT anything that is not an arXiv preprint — no blog posts, no news articles, "
            "no company announcements, no paperswithcode pages, no conference proceedings pages. "
            "The URL must contain 'arxiv.org'. If the URL is not from arxiv.org, reject immediately."
        )
    elif article.category == "ai_capability":
        category_guidance = (
            " For category ai_capability: accept content that demonstrates or discusses what AI "
            "systems can DO — concrete capabilities, not just announcements. "
            "Strong accepts: knowledge assist and enterprise AI search, voice AI and speech "
            "recognition advances, intelligent document processing and OCR, image and video "
            "generation (text-to-image, text-to-video, editing), code generation and AI coding "
            "assistants, AI-powered translation and summarisation, recommendation engines, "
            "predictive analytics, autonomous agents and robotics, and real-world demonstrations "
            "of AI capability. "
            "Score 4-5 for articles showing concrete capability with demos, benchmarks, or real "
            "deployments. Score 3 for solid capability coverage without concrete evidence. "
            "REJECT: pure market trends without capability detail (use ai_trends), research "
            "papers without a capability angle (use ai_research), tips and tutorials without "
            "a capability showcase (use genai_tips), and opinion pieces with no substance."
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
    audience_description: str = "AI practitioners and tech-savvy readers",
) -> ArticleSummary:
    """
    Summarizer Agent:
    Create a concise, skimmable summary with an eye-catching headline for a single accepted item.
    Research articles get a dedicated prompt that prioritises what-method-result over plain-English softening.
    """
    is_research = article.category in ("ai_research", "ai_research_arxiv")

    if is_research:
        system_prompt = textwrap.dedent(
            """
            You are a research digest writer. Your reader is technical but busy —
            they want to know what a paper does and why it matters in the fewest words possible.

            Given a research paper or article, produce:

            1. suggested_subject: A sharp headline with a relevant emoji (🔬 research, 🧠 models,
               📊 benchmarks, ⚡ efficiency, 🛡️ safety). Lead with the finding or capability,
               not the field. Under 12 words. OK to keep key technical terms if they are the point
               (e.g. "New Sparse Attention Cuts Transformer Cost by 3×").

            2. summary: Exactly 2 sentences — no more, no fewer.
               Sentence 1: What the paper does — the problem it tackles and the core method/approach.
               Sentence 2: The best concrete result or key takeaway (numbers are good: accuracy, speedup,
               parameter count, benchmark name). If no hard numbers exist, state the practical implication.
               Write tight. Drop all filler ("the researchers found that", "this paper presents", etc.).
               Keep technical terms that carry real meaning; explain ones that don't in plain words.

            HARD RULES:
            - Exactly 2 sentences in the summary. Not 1, not 3.
            - No bullet points, no lists, no labels inside the summary.
            - Do not start either sentence with "The paper" or "This paper".

            Output strict JSON:
            {
              "suggested_subject": "sharp headline with emoji",
              "summary": "exactly 2 sentences"
            }
            """
        ).strip()
    else:
        system_prompt = textwrap.dedent(
            """
            You are a newsletter writer producing a quick-read AI news digest.

            Given a single article, produce:

            1. suggested_subject: A punchy headline with a relevant emoji
               (🚀 launches, 🤖 AI tools, 🌐 global news, 📢 announcements, ⚖️ policy).
               Under 10 words. No jargon.

            2. summary: Exactly 2 sentences — no more, no fewer.
               Sentence 1: What happened and who/what is involved.
               Sentence 2: Why it matters or what the reader should take away.
               Write like a smart friend summarising the news. Cut every word that doesn't add meaning.
               Plain English — no buzzwords, no padding.

            HARD RULES:
            - Exactly 2 sentences. Not 1, not 3.
            - No bullet points, no lists, no labels inside the summary.
            - Do not start with "In a significant" or "In an exciting" or similar filler openers.

            Output strict JSON:
            {
              "suggested_subject": "punchy headline with emoji",
              "summary": "exactly 2 sentences"
            }
            """
        ).strip()

    content_preview = article.content[:6000] or article.snippet

    user_prompt = textwrap.dedent(
        f"""
        Category: {article.category}
        Title: {article.title}
        URL: {article.url}

        Content (may be truncated):
        ---
        {content_preview}
        ---
        """
    ).strip()

    data = chat_completion_json(system_prompt=system_prompt, user_prompt=user_prompt)

    return ArticleSummary(
        article_id=article.id,
        summary=str(data.get("summary", "")).strip(),
        suggested_subject=str(data.get("suggested_subject", "")).strip(),
    )


def compose_newsletter_section(
    category: str,
    audience: str,
    tone: str,
    items: List[Dict[str, str]],
) -> str:
    """
    Composer Agent:
    Assembles pre-written summaries into a formatted newsletter section.
    Does NOT rewrite summaries — treats them as final copy.

    `items` is a list of dicts with keys:
      - title (headline), url, summary (2 sentences, final), image_path (optional)
    """
    system_prompt = textwrap.dedent(
        """
        You assemble a quick-read AI news newsletter section from pre-written items.
        Your job is layout and structure only — do NOT rewrite, expand, or paraphrase any summary.

        Layout for the section:
        - One short section heading (reflect the category).
        - No intro sentence unless it genuinely adds context in under 8 words.
        - Each item in this exact order:
            **[Headline]** (copy exactly as given, including emoji)
            [Summary] (copy exactly as given — 2 sentences, do not alter a single word)
            ![Headline](image_path)  ← only if an image_path is provided
            Read more: <URL>
        - One blank line between items.
        - No extra labels, fields, commentary, or section dividers.
        - Plain markdown only. No HTML.

        If a summary already has 2 sentences, it is correct — do not touch it.
        """
    ).strip()

    items_text_parts: List[str] = []
    for idx, item in enumerate(items, start=1):
        image_path = item.get("image_path", "").strip()
        img_line = f"\nImage path (embed as Markdown image if present): {image_path}" if image_path else ""
        items_text_parts.append(
            textwrap.dedent(
                f"""
                Item {idx}
                Headline: {item.get("title", "")}
                URL: {item.get("url", "")}
                Summary (copy verbatim — do not change): {item.get("summary", "")}
                {img_line}
                """
            ).strip() + "\n\n---"
        )

    items_block = "\n\n".join(items_text_parts)

    user_prompt = textwrap.dedent(
        f"""
        Tone: {tone}
        Category: {category}

        {items_block}

        Assemble the newsletter section. Copy headlines and summaries exactly as given.
        """
    ).strip()

    return chat_completion(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.2)


def standardize_newsletter(
    draft: str,
    category: str,
    audience: str,
    target_max_words: int = 600,
    target_words_per_item: int = 120,
) -> tuple[str, Dict[str, Any]]:
    """
    Standardizer Agent:
    Final trim pass — enforces length and structure. Only shortens, never expands.
    Returns (standardized_text, details_dict) for logging.
    """
    word_count_before = len(draft.split())
    system_prompt = textwrap.dedent(
        """
        You are the final editor for a quick-read AI news newsletter.
        Your only job is to trim — you NEVER add words, expand summaries, or rewrite headlines.

        RULES:

        1. ITEM BOUNDARIES: Never merge content from two different items. Every story stays separate.

        2. SENTENCE CAP: Each item's summary must be exactly 2 sentences. If a summary has 3+,
           cut the least informative sentence. If it has 1, leave it — do not add a sentence.

        3. TRIM TARGETS (in order of priority if word count is too high):
           a. Cut filler openers ("It is worth noting that", "In a significant development", etc.)
           b. Cut redundant qualifiers ("very", "quite", "highly", "extremely")
           c. Tighten wordy phrases ("in order to" → "to", "at this point in time" → "now")
           d. As a last resort, cut the less important of the 2 summary sentences down to a clause.

        4. NEVER TOUCH: Headlines (including emojis), "Read more:" links, image lines, section headings.

        5. Structure per item (preserve exactly):
           **Bold headline with emoji**
           [2 sentences of summary]
           ![alt](path)  ← if present, keep as-is
           Read more: <URL>

        Respond with a single JSON object:
        - "standardized_text": the trimmed newsletter section (string)
        - "word_count_after": integer word count
        - "changes_applied": array of short strings describing what was trimmed
        """
    ).strip()

    user_prompt = textwrap.dedent(
        f"""
        Category: {category}
        Target max words: {target_max_words}
        Target per item: {target_words_per_item}
        Current word count: {word_count_before}

        Draft:
        ---
        {draft}
        ---

        Output only valid JSON: standardized_text, word_count_after, changes_applied.
        """
    ).strip()

    try:
        data = chat_completion_json(
            system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1
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




def generate_digest_headline(items: List[Dict[str, str]]) -> str:
    """
    Headline Agent:
    Given the final composer items (title + summary for each card), write
    a single teaser sentence that previews all stories without repeating
    their headlines verbatim. Used as the masthead tagline in the HTML output.
    """
    if not items:
        return "The latest in AI — research, tools, and what's moving the field."

    stories = "\n".join(
        f"- {item.get('title', '')} — {item.get('summary', '')}"
        for item in items
    )

    system_prompt = (
        "You write a single teaser sentence for an AI newsletter. "
        "Given the stories in this issue, write exactly 1 sentence that acts as a "
        "preview — hint at what is inside without repeating any headline word-for-word. "
        "Make it feel like an editorial hook: specific enough to be interesting, "
        "broad enough to cover all the stories. "
        "No emoji. No lists. One sentence only. No quotation marks."
    )

    user_prompt = f"Stories in this issue:\n{stories}\n\nWrite the 1-sentence teaser:"

    result = chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.5,
    )
    # Strip any accidental surrounding quotes or newlines
    return result.strip().strip('"\'\' ')


def article_to_dict(article: Article) -> Dict:
    return asdict(article)


def evaluation_to_dict(evaluation: ArticleEvaluation) -> Dict:
    return asdict(evaluation)


def summary_to_dict(summary: ArticleSummary) -> Dict:
    return asdict(summary)