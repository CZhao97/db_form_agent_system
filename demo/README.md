# DB-Curator Web Demo

This folder contains a static, browser-only demonstration site for DB-Curator. It is designed for branding, teaching, and lightweight exploration of the pipeline.

The page has three parts:

1. **Story mode** explaining dynamic literature construction, predicate-state verification, and the reported benchmark-scale results from the manuscript.
2. **Run mode** where visitors can run a deterministic browser simulation, load a precomputed walkthrough, or upload a compatible run JSON.
3. **Audit mode** where visitors inspect candidate identity, benchmark status, candidate funnel, predicate states, evidence cards, literature queries, Researcher-Critique trace events, and final database-row JSON.

The browser simulation does not call external APIs and does not reproduce manuscript-scale numbers. The precomputed walkthrough is saved demonstration data, not a live literature retrieval run. These modes demonstrate the control flow and user experience without requiring API keys, GPUs, or long-running jobs.

## Run Locally

From the repository root:

```bash
python -m http.server 8000
```

Open `http://localhost:8000/demo/`.

## What Visitors Can Try

- Choose a toy topic preset: DBP, blood exposome, or microbial natural products.
- Run individual workflow stages or load the precomputed walkthrough:
  - intent refinement;
  - dynamic literature construction;
  - candidate discovery;
  - predicate-state verification.
- Run the full toy pipeline and load the generated run into the viewer.
- Inspect candidates, benchmark-overlap or benchmark-missing status, predicate states, cited evidence cards, literature records, query provenance, and Researcher-Critique trace events.
- Upload a compatible run JSON export through **Load run JSON**.
- Download the currently loaded run JSON for reproducible inspection, including the final database-row JSON for each selected candidate.

## Data Interpretation

The benchmark values shown in the story section are reported manuscript-level evaluation results, including the DB-Curator versus zero-shot baseline comparison. The values in the run viewer describe only the currently loaded sample JSON or generated toy run. The bundled walkthrough is labeled as synthetic demonstration data unless replaced by a real exported run. Uploaded JSON is rendered with HTML escaping before display.

A production deployment can replace the deterministic browser functions in `app.js` with backend calls to the real DB-Curator pipeline.
