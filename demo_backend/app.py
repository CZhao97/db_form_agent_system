"""FastAPI backend for the DB-Curator public interactive demo."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .toy_pipeline import build_run, construct_literature, discover_candidates, real_mini_run, refine, verify_candidates


ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo"


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
def health() -> dict[str, Any]:
    return {"ok": True, "backend": "DB-Curator deterministic toy backend", "live_external_calls": False}


@app.post("/api/refine")
def api_refine(request: PromptRequest) -> dict[str, Any]:
    return refine(request.prompt)


@app.post("/api/search")
def api_search(request: PromptRequest) -> dict[str, Any]:
    return construct_literature(request.prompt)


@app.post("/api/discover")
def api_discover(request: PromptRequest) -> dict[str, Any]:
    return discover_candidates(request.prompt)


@app.post("/api/verify")
def api_verify(request: PromptRequest) -> dict[str, Any]:
    return verify_candidates(request.prompt)


@app.post("/api/run")
def api_run(request: PromptRequest) -> dict[str, Any]:
    return build_run(request.prompt)


@app.get("/api/samples/real-mini")
def api_real_mini() -> dict[str, Any]:
    return real_mini_run()


@app.get("/demo")
def demo_redirect() -> RedirectResponse:
    return RedirectResponse(url="/demo/")


@app.get("/demo/real_mini_run.json")
def demo_real_mini_json() -> FileResponse:
    return FileResponse(DEMO_DIR / "real_mini_run.json", media_type="application/json")


app.mount("/demo", StaticFiles(directory=DEMO_DIR, html=True), name="demo")
