# AI Digest - Changelog

## Current Technical Updates

### Collector Changes

* **OpenAI Deep Research collector:** Added an `openai_deep_research` collector that uses the OpenAI Responses API with web search enabled.
* **Legacy search collector removal:** Removed the old third-party search collector, dependency, config key, and mixed collector mode.
* **Legacy RSS collector retained:** The `deep` collector remains available for RSS/Atom feed collection.

### Category Model

Active categories are now limited to:

* `ai_trends`: trending AI news in general, including broad trends within AI.
* `genai_tips`: GenAI usage tips, techniques, practitioner workflows, and tools.
* `ai_innovations`: new AI innovations, capabilities, models, product features, and technical breakthroughs.
* `ai_research`: research papers, journal articles, preprints, conference work, or theory-heavy technical articles.

Removed categories are no longer accepted by the pipeline. `.env` category values are filtered to the active set, and CLI category inputs are validated.

### Overlap Controls

* Collection prompts now treat the four categories as mutually exclusive.
* The quality evaluator rejects items whose primary value belongs to another category.
* Accepted articles are deduplicated by URL across categories during a run so the final summarized set does not repeat the same source item in multiple categories.

### Output Pipeline

The existing flow remains: collect articles, evaluate quality, summarize accepted items, compose a newsletter section, standardize the draft, and save Markdown plus self-contained HTML output.
