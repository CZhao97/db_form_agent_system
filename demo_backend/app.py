"""FastAPI backend for the DB-Curator public interactive demo."""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any
import os
import secrets
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .toy_pipeline import build_run, construct_literature, discover_candidates, real_mini_run, refine, verify_candidates


ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo"
ACCESS_TOKEN = os.getenv("DEMO_ACCESS_TOKEN", "").strip()
RATE_LIMIT_PER_MINUTE = int(os.getenv("DEMO_RATE_LIMIT_PER_MINUTE", "60"))
_REQUEST_LOG: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client:
        return request.client.host
    return "unknown"


def _check_rate_limit(request: Request) -> None:
    now = time.time()
    key = _client_key(request)
    window = _REQUEST_LOG[key]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Demo rate limit exceeded. Please wait before trying again.")
    window.append(now)


def require_demo_access(request: Request) -> None:
    _check_rate_limit(request)
    if not ACCESS_TOKEN:
        return
    supplied = request.headers.get("x-demo-token", "")
    if not secrets.compare_digest(supplied, ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="A valid DB-Curator demo access token is required.")


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=1000)


app = FastAPI(
    title="DB-Curator Demo Backend",
    version="0.1.0",
    description="Lightweight deterministic backend for running DB-Curator toy workflow samples.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:8001", "http://localhost:8001"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/demo/")


@app.get("/api/health")
def health(request: Request) -> dict[str, Any]:
    _check_rate_limit(request)
    return {"ok": True, "backend": "DB-Curator deterministic toy backend", "live_external_calls": False, "auth_required": bool(ACCESS_TOKEN), "rate_limit_per_minute": RATE_LIMIT_PER_MINUTE}


@app.post("/api/refine")
def api_refine(payload: PromptRequest, request: Request) -> dict[str, Any]:
    require_demo_access(request)
    return refine(payload.prompt)


@app.post("/api/search")
def api_search(payload: PromptRequest, request: Request) -> dict[str, Any]:
    require_demo_access(request)
    return construct_literature(payload.prompt)


@app.post("/api/discover")
def api_discover(payload: PromptRequest, request: Request) -> dict[str, Any]:
    require_demo_access(request)
    return discover_candidates(payload.prompt)


@app.post("/api/verify")
def api_verify(payload: PromptRequest, request: Request) -> dict[str, Any]:
    require_demo_access(request)
    return verify_candidates(payload.prompt)


@app.post("/api/run")
def api_run(payload: PromptRequest, request: Request) -> dict[str, Any]:
    require_demo_access(request)
    return build_run(payload.prompt)


@app.get("/api/samples/real-mini")
def api_real_mini(request: Request) -> dict[str, Any]:
    require_demo_access(request)
    return real_mini_run()


@app.get("/demo")
def demo_redirect() -> RedirectResponse:
    return RedirectResponse(url="/demo/")


@app.get("/demo/real_mini_run.json")
def demo_real_mini_json() -> FileResponse:
    return FileResponse(DEMO_DIR / "real_mini_run.json", media_type="application/json")


app.mount("/demo", StaticFiles(directory=DEMO_DIR, html=True), name="demo")
