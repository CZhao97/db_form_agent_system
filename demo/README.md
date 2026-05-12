# DB-Curator Web Demo

This static demo visualizes the intermediate state of a DB-Curator run:

- refined user definition;
- candidate funnel metrics;
- dynamic literature set;
- candidate-level labels;
- predicate/rubric states;
- cited evidence cards;
- Researcher-Critique iteration trace.

## Run Locally

From the repository root:

```bash
python -m http.server 8000
```

Open `http://localhost:8000/demo/`.

The page loads `demo/sample_run.json` by default. Use **Load run JSON** to inspect another run exported in the same schema.


## What You Can Run

The page includes a browser-only deterministic lab. It does not call external APIs, but it demonstrates the DB-Curator control flow:

1. **Intent refinement** turns a curation request into predicates.
2. **Dynamic literature construction** builds a paper set around broad and follow-up queries.
3. **Candidate discovery** simulates entity extraction, grounding, ranking, and triage.
4. **Predicate verification** assigns candidate-level labels from rubric states.
5. **Run full pipeline** executes all steps and loads the generated toy run into the result viewer below.

This is meant for branding, teaching, and UI prototyping. A production deployment can replace the deterministic browser functions with backend calls to the real DB-Curator pipeline.
