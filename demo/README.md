# DB-Curator Web Demo

This folder contains a static, browser-only demonstration site for DB-Curator. It is designed for branding, teaching, and lightweight exploration of the pipeline.

The page has two parts:

1. **Academic story page** explaining dynamic literature construction, predicate-state verification, and the reported benchmark-scale results from the manuscript.
2. **Interactive toy lab** where visitors can run deterministic examples of the major DB-Curator workflow stages and inspect the generated toy run.

The toy lab does not call external APIs and does not reproduce manuscript-scale numbers. It demonstrates the control flow and user experience without requiring API keys, GPUs, or long-running literature retrieval jobs.

## Run Locally

From the repository root:

```bash
python -m http.server 8000
```

Open `http://localhost:8000/demo/`.

## What Visitors Can Try

- Choose a toy topic preset: DBP, blood exposome, or microbial natural products.
- Run individual workflow stages:
  - intent refinement;
  - dynamic literature construction;
  - candidate discovery;
  - predicate-state verification.
- Run the full toy pipeline and load the generated run into the viewer.
- Inspect candidates, predicate states, cited evidence cards, literature records, and Researcher-Critique trace events.
- Upload a compatible run JSON export through **Load run JSON**.
- Download the currently loaded run JSON for reproducible inspection.

## Data Interpretation

The benchmark values shown in the story section are reported manuscript-level evaluation results, including the DB-Curator versus zero-shot baseline comparison. The values in the run viewer describe only the currently loaded sample JSON or generated toy run. Uploaded JSON is rendered with HTML escaping before display.

A production deployment can replace the deterministic browser functions in `app.js` with backend calls to the real DB-Curator pipeline.
