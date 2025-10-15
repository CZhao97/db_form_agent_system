# db_form_agent_system

This repository bundles the tools, prompts, and sample notebooks that power a literature-grounded compound discovery assistant. The components revolve around three core capabilities:

- **Full-text literature search** via `FullTextJournalSearchTool`, which saves enriched results into timestamped run folders under `searching_results/`.
- **Semantic indexing and retrieval** delivered by `FullTextIndexTool` and `FullTextQueryTool`, enabling retrieval-augmented generation over the saved full texts.
- **Compound knowledge lookup** through `CompoundDatabaseTool`, combining PubChem queries with optional RDKit analytics.

📚 **Looking for the full workflow?** See [`docs/pipeline.md`](docs/pipeline.md) for a step-by-step description of the pipeline, storage layout, configuration knobs, and troubleshooting guidance.

## Quick Start

```bash
# (optional) activate your virtual environment before running the scripts
python scripts/run_searching_test.py   # generate a small literature run
python scripts/run_compound_test.py    # exercise the compound lookup tool
```

After the search script completes, inspect the newly created folder in `searching_results/` and follow the pipeline guide to build an index or query the results inside your agent.