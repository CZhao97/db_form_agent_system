from __future__ import annotations


CANONICAL_CLAIMS = {
    "Confirmed",
    "Suspected",
    "Explicit Negative Evidence",
    "Out of Scope Matrix or Context",
    "Indirect or Class-Level Only",
    "Missing Experimental Attribution",
    "Insufficient Direct Evidence",
    "Max Iteration Timeout",
    "Error",
    "Skipped (Empty)",
    "N/A",
}


def normalize_claim_label(claim: str | None) -> str:
    cleaned = (claim or "").strip()
    lowered = cleaned.lower()
    aliases = {
        "confirmed": "Confirmed",
        "suspected": "Suspected",
        "unclear": "Insufficient Direct Evidence",
        "provisional": "Insufficient Direct Evidence",
        "unclear/provisional": "Insufficient Direct Evidence",
        "not confirmed": "Insufficient Direct Evidence",
        "explicit negative evidence": "Explicit Negative Evidence",
        "out of scope matrix or context": "Out of Scope Matrix or Context",
        "indirect or class-level only": "Indirect or Class-Level Only",
        "missing experimental attribution": "Missing Experimental Attribution",
        "insufficient direct evidence": "Insufficient Direct Evidence",
        "max iteration timeout": "Max Iteration Timeout",
        "timeout": "Max Iteration Timeout",
        "error": "Error",
        "n/a": "N/A",
    }
    if lowered in aliases:
        return aliases[lowered]
    if lowered.startswith("plausible suspected"):
        return "Suspected"
    if lowered.startswith("plausible confirmed"):
        return "Confirmed"
    if lowered.startswith("plausible "):
        return "Suspected"
    if cleaned in CANONICAL_CLAIMS:
        return cleaned
    return cleaned or "Insufficient Direct Evidence"


def extract_report_claim(report: dict | None, fallback: str = "Insufficient Direct Evidence") -> str:
    report = report if isinstance(report, dict) else {}
    for key in ("final_adjudicated_claim", "claim", "researcher_claim"):
        value = report.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_claim_label(value)

    stop_reason = str(report.get("stop_reason") or "").strip().upper()
    if stop_reason == "TIMEOUT":
        return "Max Iteration Timeout"
    if stop_reason == "ERROR":
        return "Error"
    return normalize_claim_label(fallback)
