# AI Digest – Agentic Newsletter MVP

A terminal-based pipeline for an **AI Digest** newsletter: it collects AI/GenAI news per category, quality-checks and summarizes it, then composes and standardizes newsletter drafts. Multiple agents run in sequence; each step is logged to a file and to the CLI.

---

## What it does

1. **Collect** – For each category, the **Collector** fetches articles (via **Tavily** or **Deep Research** RSS/feeds, configurable); the **Quality** agent accepts/rejects each; the **Summarizer** writes short summaries for accepted items. Results are stored in `data/`.
2. **Compose** – Loads the latest run, picks top items for a category, and the **Composer** drafts a section; the **Standardizer** normalizes length and structure. The final draft is printed and saved to `output/`.

All agent steps are logged under `logs/` and echoed in the terminal.

---

## Project layout

| Path | Purpose |
|------|--------|
| `ai_digest/` | Core package: config, LLM, agents, pipeline, storage, agent logger, image collector |
| `data/` | JSON files per collection run (`digest_run_<run_id>.json`) |
| `logs/` | Agent log files per run (`collect_<run_id>.log`, `compose_<run_id>.log`) |
| `output/` | Newsletter drafts (`newsletter_<category>_<run_id>.md`) |
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
| `AI_DIGEST_CATEGORIES` | No | Comma-separated categories (default includes `ai_trends`, `ai_technology`, `ai_innovations`, `ai_research`, etc.) |
| `AI_DIGEST_COLLECTOR` | No | `tavily` (default), `deep`, or `both` – article collection backend |
| `AI_DIGEST_DEEP_FEEDS` | No | Comma-separated RSS/Atom feed URLs for deep research; if empty, built-in AI feeds are used |

- **Tavily** (`tavily`): search API only; requires `TAVILY_API_KEY`.
- **Deep Research** (`deep`): RSS/Atom feeds only (TechCrunch, VentureBeat, arXiv, Google AI, OpenAI, etc.); no Tavily key.
- **Both** (`both`): runs Tavily and Deep Research per category, merges and dedupes by URL; then Quality and Summarizer run on the combined list. Requires `TAVILY_API_KEY`.

Example `.env` (Tavily):

```
OPENAI_API_KEY=your-openai-key
TAVILY_API_KEY=your-tavily-key
OPENAI_MODEL=gpt-4.1-mini
AI_DIGEST_CATEGORIES=ai_trends,genai_tips,tools_updates,policy_ethics,ai_technology,ai_innovations
```

Example `.env` (Deep Research):

```
OPENAI_API_KEY=your-openai-key
AI_DIGEST_COLLECTOR=deep
AI_DIGEST_CATEGORIES=ai_trends,ai_technology,ai_innovations
# Optional: override default feeds (comma-separated URLs)
# AI_DIGEST_DEEP_FEEDS=https://example.com/ai.xml,https://other.com/feed/
```

Example `.env` (Both Tavily + Deep Research):

```
OPENAI_API_KEY=your-openai-key
TAVILY_API_KEY=your-tavily-key
AI_DIGEST_COLLECTOR=both
AI_DIGEST_CATEGORIES=ai_trends,ai_technology,ai_innovations
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
AI_DIGEST_CATEGORIES=ai_trends,genai_tips,tools_updates,policy_ethics,ai_technology,ai_innovations
```

**Option B – Deep Research (RSS/feeds, no Tavily key):**

```bash
OPENAI_API_KEY=your-openai-key
AI_DIGEST_COLLECTOR=deep
AI_DIGEST_CATEGORIES=ai_trends,ai_technology,ai_innovations
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

Output: newsletter draft printed in the terminal and saved under `output/newsletter_ai_trends_<run_id>.md`. Logs in `logs/`.

**Or run in two steps:**

```bash
# Step 1: Collect for all configured categories (or a subset)
python run_pipeline.py collect --categories "ai_trends,ai_technology" --max-results 6

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

Fetches articles per category (via Tavily or Deep Research, depending on `AI_DIGEST_COLLECTOR`), runs the Quality and Summarizer agents, and saves one JSON run in `data/`. Logs go to `logs/collect_<run_id>.log` and to the terminal.

**When to use:** To refresh content for all (or selected) categories. Run this before `compose` if you use the two-step workflow.

**Usage:**

```bash
python run_pipeline.py collect [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--categories "cat1,cat2"` | From env | Categories to collect (comma-separated) |
| `--audience "..."` | `"AI practitioners and leaders at a bank"` | Audience description for quality/summarizer |
| `--max-results N` | `6` | Max articles per category (Tavily or Deep Research) |

**Examples:**

```bash
# Default categories and audience
python run_pipeline.py collect

# Override categories
python run_pipeline.py collect --categories "ai_trends,genai_tips"

# Deep Research only (no Tavily key): set AI_DIGEST_COLLECTOR=deep in .env, then:
python run_pipeline.py collect --categories "ai_trends" --max-results 8

# Custom audience and more results per category
python run_pipeline.py collect --audience "CTO and tech leadership" --max-results 8
```

---

### Command: `compose`

Loads the **latest** run from `data/`, selects items for the given category, runs the Composer then the Standardizer (unless disabled), and writes the draft to `output/` and prints it. Logs go to `logs/compose_<run_id>_<time>.log` and to the terminal.

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

**Note:** If you see “No stored runs found in data/”, run `collect` first.

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
| `--category` | Yes | — | Category to collect and draft (e.g. `ai_trends`, `ai_technology`, `ai_innovations`, `ai_research`) |
| `--audience` | Yes | — | Audience (e.g. `"AI team at UnionBank"`) |
| `--tone` | Yes | — | Tone (e.g. `"professional, concise, optimistic"`) |
| `--max-results N` | No | `6` | Max articles to collect for the category |
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

# AI Technology (tech companies: Google, Apple, Microsoft, OpenAI, Meta, etc.)
python run_pipeline.py collect-and-compose \
  --category "ai_technology" \
  --audience "AI Center of Excellence Team" \
  --tone "optimistic, concise, punchy" \
  --max-results 10 \
  --sections 3 \
  --format card

# AI Innovations (models, methods, research)
python run_pipeline.py collect-and-compose \
  --category "ai_innovations" \
  --audience "AI Center of Excellence Team" \
  --tone "concise, technical, punchy" \
  --max-results 10 \
  --sections 3 \
  --format card

# AI Research (technical: models, algorithms, papers—for data scientists / researchers)
python run_pipeline.py collect-and-compose \
  --category "ai_research" \
  --audience "Data scientists and AI researchers" \
  --tone "technical, precise, research-oriented" \
  --max-results 12 \
  --sections 3 \
  --format card
```

**Result:** The draft is printed to the terminal and saved as `output/newsletter_<category>_<run_id>.md`. Logs are written to `logs/`.

**Categories:** `ai_trends`, `ai_technology`, `ai_innovations`, `ai_research` (research-focused, technical), `genai_tips`, `tools_updates`, `policy_ethics`.

---

## Agents and logs

| Agent | Role |
|-------|------|
| **Collector** | Fetches articles per category (Tavily, Deep Research RSS, or both merged, per `AI_DIGEST_COLLECTOR`); produces raw articles. |
| **Quality** | LLM accept/reject and 1–5 score per article; only accepted (score ≥ 3) are summarized. |
| **Summarizer** | LLM creates eye-catching headline and concise 2-sentence summary per accepted article. |
| **Image collector** | For each selected article, fetches the article page and saves one image (og:image or first suitable img) under `output/images/<run_id>/` (e.g. `1.jpg`, `2.png`). Used only in **card** format. |
| **Composer** | LLM drafts a full newsletter section with headlines, 2-sentence content, optional embedded image markdown, and "Read more" links. |
| **Standardizer** | LLM normalizes length and structure (headings, intro, per-item blocks, word limits); preserves image markdown. |

**Image collection (card format only):** Before composing, the pipeline tries to fetch one image per news item from the article’s page (via `og:image` or the first suitable image). Images are saved under `output/images/<run_id>/` as `1.jpg`, `2.png`, etc., and the newsletter markdown embeds them as `![Headline](images/<run_id>/1.jpg)`. You can attach or inline these when sending the email.

While `collect` or `compose` runs:

- **Terminal:** Each agent step is printed (timestamp, agent name, action, message, and optional details).
- **Files:** The same is appended to a log file in `logs/`:
  - `collect_<run_id>.log` for a collect run
  - `compose_<run_id>_<HHMMSS>.log` for a compose run

Log details include e.g. category, article title/URL, quality decision and notes, summary preview, word counts, and standardizer “changes applied”.

---

## Typical workflow

1. **One-shot (recommended for a single category)**  
   `python run_pipeline.py collect-and-compose --category "ai_trends" --audience "AI team at UnionBank" --tone "professional, concise"`  
   Collects, then composes and saves the draft to `output/`.

2. **Refresh content for many categories**  
   `python run_pipeline.py collect` (optionally `--categories "ai_trends,ai_technology"` and `--max-results 8`).

3. **Draft a section from the latest run**  
   `python run_pipeline.py compose --category "ai_trends" --audience "..." --tone "..." --sections 3`.

4. **Reuse the same data with different audience/tone**  
   Run `compose` again with different `--audience` and `--tone` (no need to re-collect).

5. **Inspect what each agent did**  
   Open the latest `logs/collect_*.log` or `logs/compose_*.log`, or scroll back in the terminal output.

6. **Edit the draft**  
   Adjust the generated file in `output/` for final copy or for poster-size layouts later.

---

## Roadmap ideas

- More agents (e.g. fact-checking, de-duplication across weeks).
- Audience presets (team / CTO / whole bank) and poster-ready export (HTML/PDF, etc.).
- Scheduled runs and delivery (email, Slack, SharePoint).
