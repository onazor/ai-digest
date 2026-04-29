from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from ai_digest.config import get_settings
from ai_digest.pipeline import (
    compose_newsletter_from_run,
    run_collection_pipeline,
)
from ai_digest.storage import load_latest_run


def _parse_categories_arg(raw: Optional[str]) -> Optional[List[str]]:
    if raw is None:
        return None
    return [c.strip() for c in raw.split(",") if c.strip()]


def cmd_collect(args: argparse.Namespace) -> None:
    settings = get_settings()
    categories = _parse_categories_arg(args.categories) or settings.default_categories

    print("Running collection pipeline...")
    print(f"Categories: {', '.join(categories)}")
    payload = run_collection_pipeline(
        categories=categories,
        audience_description=args.audience,
        max_results_per_category=args.max_results,
        max_pool=getattr(args, "max_pool", None),
    )

    print("Collection complete.")
    print(f"Run ID: {payload.get('run_id')}")
    print(f"Articles collected: {len(payload.get('articles', []))}")
    print(f"Summaries created: {len(payload.get('summaries', []))}")


def _sections_from_args(args: argparse.Namespace) -> int:
    """Number of sections (news items): --sections overrides --max-items; default 3."""
    return getattr(args, "sections", None) or getattr(args, "max_items", None) or 3


def cmd_compose(args: argparse.Namespace) -> None:
    run_payload = load_latest_run()
    if not run_payload:
        print("No stored runs found in data/. Please run 'collect' first.")
        sys.exit(1)

    category = args.category
    audience = args.audience
    tone = args.tone
    sections = _sections_from_args(args)

    print(f"Composing newsletter for category '{category}' ({sections} sections)...")
    text = compose_newsletter_from_run(
        run_payload=run_payload,
        category=category,
        audience=audience,
        tone=tone,
        max_items=sections,
        standardize=not args.no_standardize,
        target_max_words=args.target_max_words,
        target_words_per_item=args.target_words_per_item,
        output_format=getattr(args, "format", "card"),
        roundup_title=getattr(args, "roundup_title", None),
        roundup_intro=getattr(args, "roundup_intro", None),
    )

    print("\n=== Newsletter Draft ===\n")
    print(text)


def cmd_collect_and_compose(args: argparse.Namespace) -> None:
    """Run collect and compose in one command for a specific category and audience."""
    settings = get_settings()
    
    # Use the specified category, or default to first category if not provided
    category = args.category
    categories = [category] if category else settings.default_categories[:1]
    
    print("=" * 60)
    print("Step 1: Collecting and processing content...")
    print("=" * 60)
    print(f"Category: {category}")
    print(f"Audience: {args.audience}")
    
    # Run collection
    payload = run_collection_pipeline(
        categories=categories,
        audience_description=args.audience,
        max_results_per_category=args.max_results,
        max_pool=getattr(args, "max_pool", None),
    )
    
    print(f"\nCollection complete. Run ID: {payload.get('run_id')}")
    print(f"Articles collected: {len(payload.get('articles', []))}")
    print(f"Summaries created: {len(payload.get('summaries', []))}")
    
    print("\n" + "=" * 60)
    print("Step 2: Composing newsletter...")
    print("=" * 60)

    sections = _sections_from_args(args)
    print(f"Sections: {sections}, Format: {getattr(args, 'format', 'card')}")

    # Compose newsletter from the run we just created
    text = compose_newsletter_from_run(
        run_payload=payload,
        category=category,
        audience=args.audience,
        tone=args.tone,
        max_items=sections,
        standardize=not args.no_standardize,
        target_max_words=args.target_max_words,
        target_words_per_item=args.target_words_per_item,
        output_format=getattr(args, "format", "card"),
        roundup_title=getattr(args, "roundup_title", None),
        roundup_intro=getattr(args, "roundup_intro", None),
    )

    print("\n=== Newsletter Draft ===\n")
    print(text)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="AI Digest – Agentic newsletter pipeline (terminal MVP)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # collect
    collect_parser = subparsers.add_parser(
        "collect", help="Collect, quality-check, and summarize fresh content."
    )
    collect_parser.add_argument(
        "--categories",
        type=str,
        default=None,
        help="Comma-separated list of categories (overrides AI_DIGEST_CATEGORIES).",
    )
    collect_parser.add_argument(
        "--audience",
        type=str,
        default="AI practitioners and leaders at a bank",
        help="High-level description of the target audience.",
    )
    collect_parser.add_argument(
        "--max-results",
        type=int,
        default=6,
        help="Max results per category.",
    )
    collect_parser.add_argument(
        "--max-pool",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Max articles passed to the quality evaluator (deep collector only). "
            "Defaults to --max-results when not set."
        ),
    )
    collect_parser.set_defaults(func=cmd_collect)

    # compose
    compose_parser = subparsers.add_parser(
        "compose", help="Compose a newsletter draft from the latest run."
    )
    compose_parser.add_argument(
        "--category",
        type=str,
        required=True,
        help="Category to generate a newsletter section for.",
    )
    compose_parser.add_argument(
        "--audience",
        type=str,
        required=True,
        help="Description of the audience (e.g., 'AI team', 'CTO', 'whole bank').",
    )
    compose_parser.add_argument(
        "--tone",
        type=str,
        required=True,
        help="Tone description (e.g., 'professional, concise, optimistic').",
    )
    compose_parser.add_argument(
        "--sections",
        type=int,
        default=3,
        metavar="N",
        help="Fixed number of news sections (e.g. 3 = exactly 3 items). Default: 3.",
    )
    compose_parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        metavar="N",
        help="Deprecated: use --sections. Max items to include (default 3).",
    )
    compose_parser.add_argument(
        "--format",
        choices=["card", "table"],
        default="card",
        help="Output style: 'card' (emoji headlines + summaries) or 'table' (Date | Headline | Source | Summary). Default: card.",
    )
    compose_parser.add_argument(
        "--no-standardize",
        action="store_true",
        help="Skip the standardizer agent (output raw composer draft).",
    )
    compose_parser.add_argument(
        "--target-max-words",
        type=int,
        default=500,
        help="Target max total words for the standardized draft.",
    )
    compose_parser.add_argument(
        "--target-words-per-item",
        type=int,
        default=80,
        help="Target words per item in the standardized draft (2 sentences).",
    )
    compose_parser.set_defaults(func=cmd_compose)

    # collect-and-compose
    collect_compose_parser = subparsers.add_parser(
        "collect-and-compose",
        help="Collect content and compose newsletter in one command for a specific category and audience.",
    )
    collect_compose_parser.add_argument(
        "--category",
        type=str,
        required=True,
        help="Category to collect and generate newsletter for (e.g., 'ai_trends', 'genai_tips', 'ai_research_arxiv', 'ai_capability').",
    )
    collect_compose_parser.add_argument(
        "--audience",
        type=str,
        required=True,
        help="Description of the audience (e.g., 'AI team at UnionBank', 'CTO and tech leadership').",
    )
    collect_compose_parser.add_argument(
        "--tone",
        type=str,
        required=True,
        help="Tone description (e.g., 'professional, concise, optimistic').",
    )
    collect_compose_parser.add_argument(
        "--max-results",
        type=int,
        default=6,
        help="Max Tavily results to collect for the category.",
    )
    collect_compose_parser.add_argument(
        "--sections",
        type=int,
        default=3,
        metavar="N",
        help="Fixed number of news sections (e.g. 3 = exactly 3 items). Default: 3.",
    )
    collect_compose_parser.add_argument(
        "--max-pool",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Max articles passed to the quality evaluator (deep collector only). "
            "Defaults to --max-results when not set. "
            "Raise this to give the evaluator a larger pool without fetching more from the source."
        ),
    )
    collect_compose_parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        metavar="N",
        help="Deprecated: use --sections. Max items (default 3).",
    )
    collect_compose_parser.add_argument(
        "--format",
        choices=["card", "table"],
        default="card",
        help="Output style: 'card' (emoji headlines + summaries) or 'table' (Date | Headline | Source | Summary). Default: card.",
    )
    collect_compose_parser.add_argument(
        "--no-standardize",
        action="store_true",
        help="Skip the standardizer agent (card format only; ignored for table).",
    )
    collect_compose_parser.add_argument(
        "--target-max-words",
        type=int,
        default=500,
        help="Target max total words for the standardized draft (card only).",
    )
    collect_compose_parser.add_argument(
        "--target-words-per-item",
        type=int,
        default=80,
        help="Target words per item in the standardized draft (card only, 2-3 sentences).",
    )
    collect_compose_parser.set_defaults(func=cmd_collect_and_compose)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()