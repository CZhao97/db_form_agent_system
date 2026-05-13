# DB-Curator

DB-Curator is a multi-agent system for on-demand scientific database construction from open-ended user requests. It converts a natural-language curation goal into a machine-actionable rubric, builds a dynamic literature set, discovers candidate entities, and verifies each candidate through a Researcher--Critique loop with auditable evidence provenance.

The system was developed for chemistry and biomedicine use cases, including disinfection byproducts, blood exposome chemicals, drugs, endogenous metabolites, and microbial natural products. The architecture is intended to be adaptable to other scientific curation tasks by replacing the entity recognizer, grounding resources, and domain rubric.

## What Is Included

- `code/`: core DB-Curator implementation, retrieval tools, chemical grounding, candidate ranking, and verification utilities.
- `prompts/`: system prompts for refinement, discovery, query generation, literature research, and critique agents.
- `scripts/run/`: curated scripts for running topic discovery, candidate ranking, and verification stages.
- `scripts/evaluation/`: scripts for benchmark labeling, citation-support audit, overlap/manual-review preparation, and evaluation analysis.
- `scripts/offline_index/`: utilities for preparing and querying an optional offline literature metadata/full-text index.
- `manuscript/`: manuscript source, generated figures, supplementary information, and figure-generation scripts.
- `docs/`: release notes, architecture overview, and data availability notes.

Large local runtime artifacts are intentionally not included. This repository should be paired with the released data package for full benchmark reproduction.

## Repository Layout

```text
DB-Curator/
├── code/                  # Core multi-agent, retrieval, grounding, and ranking code
├── prompts/               # Prompt templates used by the agents
├── scripts/
│   ├── run/               # Main pipeline runners
│   ├── evaluation/        # Evaluation and audit scripts
│   └── offline_index/     # Optional offline-corpus preparation utilities
├── manuscript/            # Manuscript source, figures, SI, and figure scripts
├── docs/                  # Public-release documentation
├── .env.example           # Environment variable template
├── requirements.txt       # Python dependency list
└── CITATION.cff           # Citation metadata
```

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export PYTHONPATH="$PWD/code:$PYTHONPATH"
```

Edit `.env` with the API keys and local cache/index paths you intend to use. Do not commit `.env`.

Example topic definitions are provided in `examples/topics.jsonl`.

The public snapshot is intentionally source-focused. Machine-specific runner scripts from the experimental environment are not included when they depend on local paths. Use the modules in `code/` to build new runners for your environment, or pair this repository with the external benchmark/results data package for manuscript reproduction.

Full benchmark reproduction requires the external benchmark/results data package described in `docs/data_availability.md`.

## Configuration

DB-Curator can use online literature sources, optional local full-text caches, and optional offline metadata indexes. Common environment variables are listed in `.env.example`.

The implementation avoids storing secrets in code. API keys should be provided through environment variables or an untracked `.env` file.


## Interactive Demo

A static web demo is included in `demo/`. It presents DB-Curator as an academic tool story and includes a browser-only toy lab plus a real mini-run walkthrough for exploring the major workflow stages: intent refinement, dynamic literature construction, candidate discovery, and predicate-state verification.

Run the static version locally with:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000/demo/`. The benchmark values in the story section are manuscript-level results; the run viewer values describe only the loaded sample JSON or generated toy run. The page also supports run-JSON upload and download for lightweight inspection, including candidate-level audit artifacts and final database-row JSON.

To let visitors run toy workflow samples through a local backend, use the lightweight FastAPI demo service:

```bash
pip install -r demo_backend/requirements.txt
python -m uvicorn demo_backend.app:app --reload --port 8000
```

Then open `http://127.0.0.1:8000/demo/`. The web page will show `Backend connected` and route stage buttons through `/api/refine`, `/api/search`, `/api/discover`, `/api/verify`, and `/api/run`.

## Manuscript Reproduction

The manuscript source and generated figures are in `manuscript/latex/`. To rebuild the main PDF from the public snapshot:

```bash
cd manuscript/latex
pdflatex -interaction=nonstopmode -halt-on-error 348d7636602e415aacb4c9f4c07d6a38.tex
```

The supplementary information contains exact prompt snapshots and may require XeLaTeX if Unicode prompt text is edited:

```bash
xelatex -interaction=nonstopmode -halt-on-error supplementary_information.tex
```

## Data Policy

This public code snapshot does not include large downloaded papers, local caches, FAISS indexes, virtual environments, benchmark-private working folders, or intermediate run logs. Use the external data release for benchmark inputs, outputs, and audit tables.

## License

This public snapshot is released under the MIT License unless superseded by a separate institutional or journal policy.
