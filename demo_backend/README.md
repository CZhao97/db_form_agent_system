# DB-Curator Demo Backend

This lightweight FastAPI service lets visitors run deterministic toy DB-Curator workflow samples from the web demo. It does **not** call external literature APIs, LLMs, GPUs, or private local corpora.

## Run

From the repository root:

```bash
pip install -r demo_backend/requirements.txt
python -m uvicorn demo_backend.app:app --reload --port 8000
```

Open:

```text
http://127.0.0.1:8000/demo/
```

The page will automatically detect the backend and use API calls for:

- intent refinement;
- dynamic literature construction;
- candidate discovery;
- predicate-state verification;
- full toy run generation;
- loading the saved real mini-run export.

If the backend is not running, the static page falls back to the browser-only simulation.

### Optional Access Control

For a public or shared demo, set an access token before starting the backend:

```bash
export DEMO_ACCESS_TOKEN=choose-a-reviewer-code
export DEMO_RATE_LIMIT_PER_MINUTE=60
python -m uvicorn demo_backend.app:app --reload --port 8000
```

Visitors enter the code in the web page. Backend API calls include it as `X-Demo-Token`. Without the token, the backend returns `401`; static browser-only fallback remains harmless because it does not call APIs, LLMs, external tools, or local corpora.
