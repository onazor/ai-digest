# AI Digest – Agentic Newsletter MVP

A terminal-based pipeline for an **AI Digest** newsletter: it collects AI/GenAI news per category, quality-checks and summarizes it, then composes and standardizes newsletter drafts. Multiple agents run in sequence; each step is logged to a file and to the CLI.

---

## What it does

1. **Collect** – For each category, the **Collector** fetches articles (via **Tavily** or **Deep Research** RSS/feeds, configurable); the **Quality** agent accepts/rejects each; the **Summarizer** writes short summaries for accepted items. Results are stored in `data/`. Articles within a category are now evaluated and summarized **concurrently** (5-worker pool), and when using `both` collector mode, Tavily and Deep Research run in parallel.
2. **Compose** – Loads the latest run, picks top items for a category, and the **Composer** drafts a section; the **Standardizer** normalizes length and structure. The final draft is printed and saved to `output/` as both a **Markdown** and a **self-contained HTML** file (with base64-embedded images).

All agent steps are logged under `logs/` and echoed in the terminal.

---

## Project layout

| Path | Purpose |
|------|--------|
| `ai_digest/` | Core package: config, LLM, agents, pipeline, storage, agent logger, image collector |
| `ai_digest/templates/newsletter_card.html` | Email-safe Jinja2 template (table-based layout, orange masthead, responsive stacking) |
| `ai_digest/formatter.py` | Renders newsletter cards as a self-contained HTML string; converts images to base64 |
| `data/` | JSON files per collection run (`digest_run_<run_id>.json`) |
| `logs/` | Agent log files per run (`collect_<run_id>.log`, `compose_<run_id>.log`) |
| `output/` | Newsletter drafts – both `newsletter_<category>_<run_id>.md` and `newsletter_<category>_<run_id>.html` |
| `output/images/<run_id>/` | One image per news item (e.g. `1.jpg`, `2.png`) for embedding in the newsletter |
| `run_pipeline.py` | CLI entrypoint |

---

## Setup

### 1. Environment

From the project root (`ai-digest`):

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configuration

Set these (e.g. in your shell or a `.env` file in the project root):

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI-compatible API key |
| `TAVILY_API_KEY` | When `AI_DIGEST_COLLECTOR=tavily` or `both` | Tavily search API key |
| `OPENAI_MODEL` | No | Model name (default: `gpt-4.1-mini`) |
| `AI_DIGEST_CATEGORIES` | No | Comma-separated categories (default: `ai_trends`, `genai_tips`, `ai_innovations`, `ai_research`, `ai_research_arxiv`, `ai_capability`) |
| `AI_DIGEST_COLLECTOR` | No | `tavily` (default), `deep`, or `both` – article collection backend |
| `AI_DIGEST_DEEP_FEEDS` | No | Comma-separated RSS/Atom feed URLs for deep research; if empty, built-in AI feeds are used |

- **Tavily** (`tavily`): search API only; requires `TAVILY_API_KEY`.
- **Deep Research** (`deep`): RSS/Atom feeds only (TechCrunch, VentureBeat, arXiv, Google AI, OpenAI, etc.); no Tavily key needed. All 30+ feeds now fetch concurrently, reducing worst-case time from ~750s to ~25s.
- **Both** (`both`): runs Tavily and Deep Research concurrently per category, merges and dedupes by URL; then Quality and Summarizer run on the combined list. Requires `TAVILY_API_KEY`.

Example `.env` (Tavily):

```
OPENAI_API_KEY=your-openai-key
TAVILY_API_KEY=your-tavily-key
OPENAI_MODEL=gpt-4.1-mini
AI_DIGEST_CATEGORIES=ai_trends,genai_tips,ai_innovations,ai_research,ai_research_arxiv,ai_capability
```

Example `.env` (Deep Research):

```
OPENAI_API_KEY=your-openai-key
AI_DIGEST_COLLECTOR=deep
AI_DIGEST_CATEGORIES=ai_trends,ai_innovations,ai_research_arxiv
# Optional: override default feeds (comma-separated URLs)
# AI_DIGEST_DEEP_FEEDS=https://example.com/ai.xml,https://other.com/feed/
```

Example `.env` (Both Tavily + Deep Research):

```
OPENAI_API_KEY=your-openai-key
TAVILY_API_KEY=your-tavily-key
AI_DIGEST_COLLECTOR=both
AI_DIGEST_CATEGORIES=ai_trends,ai_innovations,ai_research,ai_capability
```

---

## How to run completely (from scratch)

Run everything from the **project root** (`ai-digest`). Use `python` or `python3` depending on your system.

### 1. One-time setup

```bash
cd ai-digest
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

Create a `.env` file in the project root (or export variables in your shell).

**Option A – Tavily (search API):**

```bash
OPENAI_API_KEY=your-openai-key
TAVILY_API_KEY=your-tavily-key
OPENAI_MODEL=gpt-4.1-mini
AI_DIGEST_CATEGORIES=ai_trends,genai_tips,ai_innovations,ai_research,ai_research_arxiv,ai_capability
```

**Option B – Deep Research (RSS/feeds, no Tavily key):**

```bash
OPENAI_API_KEY=your-openai-key
AI_DIGEST_COLLECTOR=deep
AI_DIGEST_CATEGORIES=ai_trends,ai_innovations,ai_research_arxiv
```

### 3. Run the pipeline

**Full run in one command (collect + compose for one category):**

```bash
python run_pipeline.py collect-and-compose \
  --category "ai_trends" \
  --audience "AI team at UnionBank" \
  --tone "professional, concise, optimistic" \
  --max-results 8 \
  --sections 3
```

Output: newsletter draft printed in the terminal and saved under `output/` as both `.md` and `.html` files. Logs in `logs/`.

**Or run in two steps:**

```bash
# Step 1: Collect for all configured categories (or a subset)
python run_pipeline.py collect --categories "ai_trends,ai_innovations" --max-results 6

# Step 2: Compose a section from the latest run for one category
python run_pipeline.py compose \
  --category "ai_trends" \
  --audience "AI team at UnionBank" \
  --tone "professional, concise, optimistic" \
  --sections 3
```

---

## How to run each command

All commands are run from the **project root** (`ai-digest`). Use `python` or `python3` as appropriate.

| Command | What it does |
|---------|----------------|
| `collect` | Fetch articles (Tavily or Deep Research), run Quality + Summarizer, save one run to `data/`. |
| `compose` | Load latest run, draft a newsletter section for one category, save to `output/`. (Run `collect` first.) |
| `collect-and-compose` | Run `collect` for one category then `compose` in one go; draft saved to `output/`. |

### Command: `collect`

Fetches articles per category (via Tavily or Deep Research, depending on `AI_DIGEST_COLLECTOR`), runs the Quality and Summarizer agents **concurrently**, and saves one JSON run in `data/`. Images are also fetched in parallel. Logs go to `logs/collect_<run_id>.log` and to the terminal.

**When to use:** To refresh content for all (or selected) categories. Run this before `compose` if you use the two-step workflow.

**Usage:**

```bash
python run_pipeline.py collect [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--categories "cat1,cat2"` | From env | Categories to collect (comma-separated) |
| `--audience "..."` | `"AI practitioners and leaders at a bank"` | Audience description for quality/summarizer |
| `--max-results N` | `6` | Max articles per category passed to the collector |
| `--max-pool N` | — | Max articles passed to the quality evaluator, independent of `--max-results` |

**Examples:**

```bash
# Default categories and audience
python run_pipeline.py collect

# Override categories
python run_pipeline.py collect --categories "ai_trends,genai_tips"

# Deep Research only (no Tavily key): set AI_DIGEST_COLLECTOR=deep in .env, then:
python run_pipeline.py collect --categories "ai_trends" --max-results 8

# Custom audience and broader evaluator pool
python run_pipeline.py collect --audience "CTO and tech leadership" --max-results 8 --max-pool 20
```

---

### Command: `compose`

Loads the **latest** run from `data/`, selects items for the given category, runs the Composer then the Standardizer (unless disabled), and writes the draft to `output/` as both `.md` and `.html` and prints it. Logs go to `logs/compose_<run_id>_<time>.log` and to the terminal.

**When to use:** After you have run `collect` at least once. Use when you want to generate or regenerate a newsletter section from existing run data (e.g. different audience/tone or format without re-collecting).

**Usage:**

```bash
python run_pipeline.py compose --category CATEGORY --audience "..." --tone "..." [OPTIONS]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--category` | Yes | — | Category to draft (e.g. `ai_trends`, `genai_tips`) |
| `--audience` | Yes | — | Audience (e.g. `"AI team at UnionBank"`) |
| `--tone` | Yes | — | Tone (e.g. `"professional, concise, optimistic"`) |
| `--sections N` | No | `3` | Number of news sections (items) in the draft |
| `--format` | No | `card` | `card` (emoji headlines + summaries + images) or `table` (Date \| Headline \| Source \| Summary) |
| `--no-standardize` | No | off | Skip Standardizer (card only; ignored for table) |
| `--target-max-words N` | No | `500` | Target total words for standardized draft (card only) |
| `--target-words-per-item N` | No | `80` | Target words per item (card only) |

**Examples:**

```bash
# Card format, 3 sections (default)
python run_pipeline.py compose \
  --category "ai_trends" \
  --audience "AI team at UnionBank" \
  --tone "professional, concise, optimistic" \
  --sections 3

# Table format (Date | Headline | Source | Summary)
python run_pipeline.py compose \
  --category "ai_trends" \
  --audience "AI team at UnionBank" \
  --tone "concise" \
  --sections 3 \
  --format table

# More sections and longer draft
python run_pipeline.py compose \
  --category "genai_tips" \
  --audience "AI team at UnionBank" \
  --tone "friendly, practical" \
  --sections 4 \
  --target-max-words 800 \
  --target-words-per-item 150

# Raw draft only (no standardizer)
python run_pipeline.py compose \
  --category "ai_trends" \
  --audience "CTO and tech leadership" \
  --tone "strategic, concise" \
  --no-standardize
```

**Note:** If you see "No stored runs found in data/", run `collect` first.

---

### Command: `collect-and-compose`

Runs **collect** then **compose** in one command for a single category. Uses the same collector as `collect` (Tavily or Deep Research per `AI_DIGEST_COLLECTOR`).

**When to use:** When you want fresh content and a newsletter draft in one go, without running `collect` and `compose` separately.

**Usage:**

```bash
python run_pipeline.py collect-and-compose --category CATEGORY --audience "..." --tone "..." [OPTIONS]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--category` | Yes | — | Category to collect and draft (e.g. `ai_trends`, `ai_innovations`, `ai_research`, `ai_research_arxiv`, `ai_capability`) |
| `--audience` | Yes | — | Audience (e.g. `"AI team at UnionBank"`) |
| `--tone` | Yes | — | Tone (e.g. `"professional, concise, optimistic"`) |
| `--max-results N` | No | `6` | Max articles to collect for the category |
| `--max-pool N` | No | — | Max articles passed to the quality evaluator, independent of `--max-results` |
| `--sections N` | No | `3` | Number of news sections (items) in the draft |
| `--format` | No | `card` | `card` or `table` (Date \| Headline \| Source \| Summary) |
| `--no-standardize` | No | off | Skip Standardizer (card only) |
| `--target-max-words N` | No | `500` | Target max total words (card only) |
| `--target-words-per-item N` | No | `80` | Target words per item (card only) |

**Examples:**

```bash
# Minimal: one category, default sections and format
python run_pipeline.py collect-and-compose \
  --category "ai_trends" \
  --audience "AI team at UnionBank" \
  --tone "professional, concise, optimistic"

# More sources and 4 sections (card format)
python run_pipeline.py collect-and-compose \
  --category "genai_tips" \
  --audience "CTO and tech leadership" \
  --tone "strategic, concise" \
  --max-results 8 \
  --sections 4

# Table format (Date | Headline | Source | Summary)
python run_pipeline.py collect-and-compose \
  --category "ai_trends" \
  --audience "AI team at UnionBank" \
  --tone "concise" \
  --sections 3 \
  --format table

# AI Innovations (capability breakthroughs and model releases)
python run_pipeline.py collect-and-compose \
  --category "ai_innovations" \
  --audience "AI Center of Excellence Team" \
  --tone "concise, technical, punchy" \
  --max-results 10 \
  --sections 3 \
  --format card

# AI Research (papers and preprints from general sources)
python run_pipeline.py collect-and-compose \
  --category "ai_research" \
  --audience "Data scientists and AI researchers" \
  --tone "technical, precise, research-oriented" \
  --max-results 12 \
  --sections 3 \
  --format card

# AI Research – arXiv only (strictly locked to arxiv.org)
python run_pipeline.py collect-and-compose \
  --category "ai_research_arxiv" \
  --audience "Data scientists and AI researchers" \
  --tone "technical, precise, research-oriented" \
  --max-results 12 \
  --sections 3 \
  --format card

# AI Capability (knowledge assist, voice AI, intelligent document processing, video/image generation, etc.)
python run_pipeline.py collect-and-compose \
  --category "ai_capability" \
  --audience "AI Center of Excellence Team" \
  --tone "professional, concise, optimistic" \
  --max-results 10 \
  --sections 3 \
  --format card
```

**Result:** The draft is printed to the terminal and saved as `output/newsletter_<category>_<run_id>.md` and `output/newsletter_<category>_<run_id>.html`. Logs are written to `logs/`.

**Categories:** `ai_trends`, `genai_tips`, `ai_innovations`, `ai_research`, `ai_research_arxiv`, `ai_capability`.

> **Note:** `ai_technology`, `tools_updates`, and `policy_ethics` have been removed. `ai_technology` content is now covered by `ai_innovations`; `tools_updates` content is now covered by `ai_trends`.

---

## Agents and logs

| Agent | Role |
|-------|------|
| **Collector** | Fetches articles per category (Tavily, Deep Research RSS, or both merged, per `AI_DIGEST_COLLECTOR`); produces raw articles. Deep Research now fetches all 30+ feeds concurrently. |
| **Quality** | LLM accept/reject and 1–5 score per article using category-specific criteria; articles within a category are evaluated concurrently. Only accepted items (score ≥ 3) are summarized. |
| **Summarizer** | LLM creates eye-catching headline and concise summary per accepted article. General categories use a plain-English impact-focused prompt; research categories use a structured prompt preserving technical terms and concrete results. Summarization runs concurrently per category. |
| **Image collector** | For each selected article, fetches the article page and saves one image (`og:image` or first suitable `img`) under `output/images/<run_id>/`. Images are fetched in parallel (reducing ~30s to ~10s for 3 articles). Used only in **card** format. |
| **Composer** | LLM drafts a full newsletter section with headlines, summaries, optional embedded image markdown, and "Read more" links. Operates at low temperature (0.2) and copies headlines and summaries verbatim — no creative rewriting. |
| **Standardizer** | LLM normalizes length and structure (headings, intro, per-item blocks, word limits); preserves image markdown. Operates at very low temperature (0.1) and only trims — never expands. Trim priority: filler openers → redundant qualifiers → wordy phrases → sentence shortening. |
| **Deduplicator** | Runs before the final item slice. Uses named entity overlap (0.45 threshold) and text similarity (0.38 threshold) to remove same-story duplicates. Research categories skip the entity signal to avoid false positives. |
| **Headline generator** | Reads the final composer items and generates a single teaser sentence used as the masthead tagline in the HTML output. |

**Image collection (card format only):** Before composing, the pipeline fetches one image per news item from the article's page (via `og:image` or the first suitable image). Images are saved under `output/images/<run_id>/` as `1.jpg`, `2.png`, etc., and the newsletter markdown embeds them as `![Headline](images/<run_id>/1.jpg)`. The HTML output has all images embedded as base64.

While `collect` or `compose` runs:

- **Terminal:** Each agent step is printed (timestamp, agent name, action, message, and optional details).
- **Files:** The same is appended to a log file in `logs/`:
  - `collect_<run_id>.log` for a collect run
  - `compose_<run_id>_<HHMMSS>.log` for a compose run

Log details include e.g. category, article title/URL, quality decision and notes, summary preview, word counts, and standardizer "changes applied".

---

## Typical workflow

1. **One-shot (recommended for a single category)**
   `python run_pipeline.py collect-and-compose --category "ai_trends" --audience "AI team at UnionBank" --tone "professional, concise"`
   Collects, then composes and saves the draft (`.md` + `.html`) to `output/`.

2. **Refresh content for many categories**
   `python run_pipeline.py collect` (optionally `--categories "ai_trends,ai_innovations"` and `--max-results 8`).

3. **Draft a section from the latest run**
   `python run_pipeline.py compose --category "ai_trends" --audience "..." --tone "..." --sections 3`.

4. **Reuse the same data with different audience/tone**
   Run `compose` again with different `--audience` and `--tone` (no need to re-collect).

5. **Inspect what each agent did**
   Open the latest `logs/collect_*.log` or `logs/compose_*.log`, or scroll back in the terminal output.

6. **Edit the draft**
   Adjust the generated `.md` or `.html` file in `output/` for final copy before sending.

---

## Roadmap

- **Category refinement parity:** Bring `ai_trends`, `genai_tips`, and `ai_innovations` search precision and content quality up to the same standard as the research categories.
- **Deduplication improvements:** Refine entity overlap and text similarity thresholds to reduce same-story slip-through, particularly in `ai_innovations`.
- **Graphical User Interface (GUI):** Transition from CLI and `.env` configuration to a dedicated front-end UI for easier daily operations.
- **Cross-functional feedback:** Expand pilot distribution to other departments and working groups to align the digest with broader organizational needs.
- **Non-technical summaries ("Layman" mode):** Add a processing layer that provides jargon-free summaries for non-technical stakeholders.
- **Scheduled runs and delivery:** Email, Slack, or SharePoint delivery integration.