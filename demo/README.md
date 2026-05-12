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
