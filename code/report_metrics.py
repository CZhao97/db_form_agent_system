from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _safe_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _count_index_rows(results_dir: str | None) -> int | None:
    if not isinstance(results_dir, str) or not results_dir.strip():
        return None
    index_path = Path(results_dir) / "index.csv"
    if not index_path.exists():
        return None
    try:
        with index_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return sum(1 for _ in reader)
    except Exception:
        return None


def _count_unique_evidence_sources(evidence: list[dict[str, Any]] | Any) -> int:
    if not isinstance(evidence, list):
        return 0
    return len(
        {
            str(item.get("id") or "").strip()
            for item in evidence
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
    )


def summarize_report_metrics(report: dict | None) -> dict[str, Any]:
    report = report if isinstance(report, dict) else {}
    evidence = report.get("evidence") if isinstance(report.get("evidence"), list) else []
    final_evidence_count = _safe_len(evidence)
    final_supporting_source_count = _count_unique_evidence_sources(evidence)
    index_paper_count = _count_index_rows(report.get("results_dir"))

    tokens_used = report.get("tokens_used")
    stop_reason = str(report.get("stop_reason") or "").strip().upper()
    if stop_reason in {"TIMEOUT", "ERROR"} and tokens_used in (0, "0"):
        tokens_used = None

    cost_usd = report.get("cost_usd")
    if stop_reason in {"TIMEOUT", "ERROR"} and cost_usd in (0, "0", 0.0):
        cost_usd = None

    metrics = {
        "index_paper_count": index_paper_count,
        "retrieved_paper_count": index_paper_count,
        "papers_analyzed": index_paper_count,
        "raw_evidence_items": index_paper_count,
        "final_evidence_count": final_evidence_count,
        "evidence_count": final_evidence_count,
        "final_supporting_source_count": final_supporting_source_count,
        "supporting_source_count": final_supporting_source_count,
        "evidence_depth": None,
        "tokens_used": tokens_used,
        "cost_usd": cost_usd,
    }
    return metrics

