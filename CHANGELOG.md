# AI Digest – Changelog
**Prepared by:** Yvhan

---

## **Changelog & Technical Updates**

### **`agents.py`**
* **Simplified `ArticleSummary` Dataclass:** Removed deprecated fields (`key_points`, `why_this_matters`, `technical_specs`, `industry_impact`). The dataclass is now streamlined to three essential fields: `article_id`, `summary`, and `suggested_subject`.
* **Category-Specific Tavily Queries:** Replaced the generic fallback with dedicated search queries for every active category. Queries are now precision-targeted and explicitly exclude cross-category content.
* **Tailored Search Parameters:** * `ai_research` and `ai_research_arxiv` use `topic: "news"` to capture recent publications, with `ai_research_arxiv` strictly pinned to `arxiv.org` via `include_domains`. 
    * `genai_tips` utilizes `topic: "general"` to capture quality practitioner content that isn't breaking news. 
    * `ai_trends` and `ai_innovations` use `topic: "news"`.
* **New Category (`ai_research_arxiv`):** Created a strictly locked category for arXiv content. This enforces arXiv exclusivity at every layer: Tavily `include_domains`, deep research `ARXIV_ONLY_FEEDS`, a hard URL filter, and an instant evaluator rejection for non-arXiv URLs.
* **Category Consolidation:** Streamlined the active categories down to five (`ai_trends`, `genai_tips`, `ai_innovations`, `ai_research`, `ai_research_arxiv`). `ai_technology` was absorbed into `ai_innovations`, `tools_updates` into `ai_trends`, and `policy_ethics` was removed entirely.
* **Rewritten Quality Evaluator Rules:** Implemented precise accept/reject criteria tailored to specific audiences:
    * `ai_innovations`: Evaluates capability breakthroughs and industry releases based on concrete technical detail.
    * `ai_trends`: Requires evidence of genuine traction (adoption data, widespread coverage); rejects single-company announcements.
    * `genai_tips`: Calibrated for practitioners/data scientists; rejects beginner content.
    * `ai_research`: Strictly limits to publications and preprints.
    * `ai_research_arxiv`: Strictly rejects non-arxiv.org URLs.
* **Research-Aware Summarizer Branching:** General categories now use a plain-English prompt focusing on impact. Research categories use a dedicated prompt that prescribes a strict sentence structure (problem + method, then concrete results/numbers), preserves technical terms, and bans filler.
* **Strict Assembly Composer:** Lowered temperature from 0.4 to 0.2. The prompt now explicitly forbids creative rewriting, instructing the model to copy headlines and summaries verbatim and focus purely on layout and structure.
* **Trim-Only Standardizer:** Lowered temperature to 0.1 and explicitly forbade expanding summaries. It now uses a prioritized trim checklist: cut filler openers first, redundant qualifiers second, wordy phrases third, and shorten sentences only as a last resort.
* **Added `generate_digest_headline()`:** A new function that reads the final composer items and generates a single teaser sentence previewing all stories without verbatim repetition, used as the masthead tagline in the HTML.

### **`pipeline.py`**
* **Parallelization Sweeps:** * **Quality Evaluation:** Articles within a category are now evaluated concurrently using `ThreadPoolExecutor(max_workers=5)` instead of sequentially.
    * **Summarization:** Accepted articles are summarized concurrently under a 5-worker pool.
    * **Image Collection:** Images are fetched simultaneously, reducing collection time for 3 articles from ~30s down to ~10s.
    * **Dual Collection:** When `collector_type = "both"`, Tavily and Deep Research run concurrently in a 2-worker pool.
* **New `max_pool` Parameter:** Added an argument to `run_collection_pipeline` (exposed via `--max-pool` on the CLI) to control how many articles pass to the quality evaluator, independent of `--max-results`.
* **Quota Exhaustion Handler:** `_is_quota_exhausted()` now catches OpenAI `insufficient_quota` errors and halts the pipeline immediately with a billing link, replacing the old behavior of silently logging errors and continuing.
* **HTML Output Generation:** A self-contained `.html` file (with base64 embedded images) is now generated after every compose run and saved to the `output/` directory alongside the markdown file.
* **Story Deduplication:** Added `_deduplicate_by_story()`, running right before the final `[:max_items]` slice. It utilizes a primary named entity overlap signal (0.45 threshold) to catch same-story/different-angle articles, and a secondary text similarity signal (0.38 threshold) for near-identical rewrites. Research categories skip the entity signal to avoid false positives on the "arxiv" entity.
* **Headline Integration:** Wired `generate_digest_headline` to run after the standardizer, passing its result to the HTML renderer as `digest_headline`.

### **`deep_research.py`**
* **Parallel RSS Fetching:** All 30+ feeds now fetch concurrently using `ThreadPoolExecutor(max_workers=20)`, preserving feed order for deterministic deduplication. This dropped worst-case execution time from ~750s to ~25s.
* **Expanded arXiv Feeds:** Increased feeds from 3 to 9 by adding `cs.CL`, `cs.CV`, `cs.NE`, `cs.RO`, `cs.IR`, and `eess.SP`.
* **Added `ARXIV_ONLY_FEEDS` Constant:** Bypasses default and user-configured feeds entirely when the `ai_research_arxiv` category is selected.
* **Added `_sort_arxiv_first()`:** Prioritizes arXiv entries to the top (sorted by date) for research categories, preventing papers from getting buried under general tech news.
* **Hard URL Filter:** Implemented a final backstop filter for `ai_research_arxiv` that removes any non-arxiv.org entries before evaluation.
* **Removed Pool Cap:** Deleted the hardcoded `min(max_results * 2, 30)` cap. `max_results` is now passed directly to the collector, giving users full control.
* **Updated Category Keywords:** Expanded `ai_trends` with adoption signals, rewrote `ai_innovations` around capability and model releases to avoid research overlap, emptied `ai_research_arxiv` (handled by URL filtering), and removed deprecated categories.

### **New Files: HTML Formatting & Templating**
* **`formatter.py` (New):** Renders newsletter cards as a self-contained HTML string via a Jinja2 template. Converts all images to base64 and accepts the optional `digest_headline` for the masthead.
* **`ai_digest/templates/newsletter_card.html` (New):** An email-safe Jinja2 template featuring a table-based layout (no flexbox to bypass Gmail/Outlook stripping). Design includes white cards, an orange top-border accent (`#e85d04`), an orange masthead banner with the generated teaser, responsive stacking, and a pilot feedback footer linking to a Microsoft Forms survey.

### **`storage.py`, `config.py` & `run_pipeline.py`**
* **`storage.py`:** Added `save_newsletter_html()` to save the rendered HTML to the `output/` directory.
* **`config.py`:** Updated default categories to match the new consolidated list (`ai_trends`, `genai_tips`, `ai_innovations`, `ai_research`, `ai_research_arxiv`).
* **`run_pipeline.py`:** Added the `--max-pool` argument to both `collect` and `collect-and-compose` subcommands. Updated the help text for the `--category` argument to include `ai_research_arxiv`.

---

## **Recommendations & Future Work**

### **Technical Findings & Optimization Goals**
* **Category Refinement Parity:** While the `ai_research` and `ai_research_arxiv` categories have seen substantial performance upgrades in this iteration, future development should prioritize bringing `ai_trends`, `genai_tips`, and `ai_innovations` up to the same standard of search precision and content quality.
* **Deduplication Improvements:** The current deduplication logic occasionally allows similar stories to slip through, which is most noticeable in the `ai_innovations` category. While temporarily mitigated by increasing the `--max-results` parameter to broaden the pool, refining the deduplication function's algorithms (entity overlap and text similarity thresholds) is a high-priority technical objective.

### **Team Recommendations & User Experience**
* **Graphical User Interface (GUI) Development:** Transition from the current CLI and `.env` configuration model to a dedicated front-end UI. This will streamline daily operations and make the tool accessible to operators who are less comfortable with command-line interfaces.
* **Cross-Functional Feedback Integration:** Expand pilot distribution to other departments and working groups across the bank. Gathering diverse perspectives will ensure the digest aligns with broader organizational needs and varied use cases.
* **Non-Technical Summaries ("Layman" Mode):** Introduce a processing layer or dedicated section that provides jargon-free, simplified article summaries. This will significantly improve readability and comprehension for non-technical stakeholders consuming the digest.