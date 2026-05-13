"""Deterministic toy pipeline used by the public web demo backend.

This module intentionally does not call LLMs, external literature APIs, or local
private corpora. It provides a small runnable backend that demonstrates the
DB-Curator control flow with safe, deterministic artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import re
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo"


@dataclass(frozen=True)
class Scenario:
    key: str
    definition: str
    mandatory: list[str]
    exclusions: list[str]
    papers: list[tuple[str, str, str, str, str]]
    candidates: list[tuple[str, str, int, str]]


SCENARIOS: dict[str, Scenario] = {
    "dbp": Scenario(
        key="dbp",
        definition=(
            "A database entry must be a specific chemical entity formed during "
            "water disinfection and supported by primary literature evidence in "
            "a water-treatment or drinking-water context."
        ),
        mandatory=[
            "specific chemical identity",
            "water disinfection context",
            "formation or occurrence evidence",
            "not reagent/context-only",
        ],
        exclusions=["solvent role only", "analytical standard only", "precursor but not DBP"],
        papers=[
            ("P1", "Europe PMC", "Formation of halogenated aldehydes during chlorination", "full text", "broad topic query"),
            ("P2", "Semantic Scholar", "High-resolution screening of nitrogenous DBPs", "abstract + metadata", "candidate context query"),
            ("P3", "Publisher PDF", "Iodo-phenolic byproducts in chloraminated water", "full text", "critique follow-up"),
            ("P4", "Local corpus", "Benchmark context for regulated DBPs", "metadata", "identity grounding"),
        ],
        candidates=[
            ("C1", "Chloroform", 67, "frequent measured DBP with grounded synonym TCM"),
            ("C2", "Trichloroacetaldehyde", 24, "specific carbonyl DBP with direct chlorination context"),
            ("C3", "2,4,6-triiodophenol", 9, "rare candidate requiring follow-up formation evidence"),
            ("C4", "Acetonitrile", 31, "high mention count but likely solvent/context artifact"),
        ],
    ),
    "blood": Scenario(
        key="blood",
        definition=(
            "A database entry must be a specific chemical entity reported in "
            "human blood or systemic circulation and linked to external exposure, "
            "exposure response, or exposome literature."
        ),
        mandatory=[
            "specific chemical identity",
            "human blood/systemic matrix",
            "exposure-linked context",
            "primary literature or biomonitoring evidence",
        ],
        exclusions=["method contaminant only", "non-human matrix only", "class-level mention only"],
        papers=[
            ("P1", "Europe PMC", "Human biomonitoring of perfluoroalkyl substances in serum", "full text", "broad topic query"),
            ("P2", "OpenAlex", "Blood exposome signatures after dietary exposure", "metadata", "topic expansion"),
            ("P3", "Publisher PDF", "Serum detection of organophosphate metabolites", "full text", "candidate follow-up"),
            ("P4", "Local corpus", "Population-scale plasma exposomics", "full text", "rubric follow-up"),
        ],
        candidates=[
            ("C1", "Perfluorooctanoic acid", 54, "measured in human serum with exposure context"),
            ("C2", "Bisphenol A glucuronide", 18, "specific metabolite in blood/plasma exposure studies"),
            ("C3", "Diethyl phosphate", 11, "possible exposure metabolite requiring matrix-specific evidence"),
            ("C4", "Methanol", 22, "common reagent/context term likely not releasable"),
        ],
    ),
    "microbial": Scenario(
        key="microbial",
        definition=(
            "A database entry must be a specific natural product produced by a "
            "microorganism and supported by organism-linked primary literature evidence."
        ),
        mandatory=[
            "specific chemical identity",
            "microbial producer context",
            "natural product evidence",
            "not synthetic analog only",
        ],
        exclusions=["plant-only source", "synthetic intermediate only", "class-level mention only"],
        papers=[
            ("P1", "Semantic Scholar", "Genome-guided discovery of bacterial polyketides", "abstract + metadata", "broad topic query"),
            ("P2", "Europe PMC", "Isolation of cyclic peptides from Streptomyces species", "full text", "organism query"),
            ("P3", "Publisher PDF", "Marine actinomycete metabolites with antimicrobial activity", "full text", "candidate follow-up"),
            ("P4", "Local corpus", "Natural product atlas cross-reference context", "metadata", "identity grounding"),
        ],
        candidates=[
            ("C1", "Surfactin", 45, "specific bacterial lipopeptide with producer context"),
            ("C2", "Actinomycin D", 32, "microbial natural product with organism-linked evidence"),
            ("C3", "Marinopyrrole A", 8, "rare marine candidate requiring source verification"),
            ("C4", "Palmitic acid", 29, "common lipid likely contextual rather than topic-specific"),
        ],
    ),
}


def scenario_for_prompt(prompt: str) -> Scenario:
    text = prompt.lower()
    if "blood" in text or "exposome" in text:
        return SCENARIOS["blood"]
    if "microbial" in text or "natural product" in text:
        return SCENARIOS["microbial"]
    return SCENARIOS["dbp"]


def refine(prompt: str) -> dict[str, Any]:
    scenario = scenario_for_prompt(prompt)
    return {
        "stage": "Intent refinement",
        "scenario": scenario.key,
        "user_request": prompt,
        "refined_definition": scenario.definition,
        "mandatory_predicates": scenario.mandatory,
        "exclusion_predicates": scenario.exclusions,
    }


def construct_literature(prompt: str) -> dict[str, Any]:
    scenario = scenario_for_prompt(prompt)
    papers = [
        {"id": pid, "source": source, "title": title, "status": status, "triggered_by": trigger, "query": query_for_paper(prompt, title, trigger)}
        for pid, source, title, status, trigger in scenario.papers
    ]
    return {
        "stage": "Dynamic literature construction",
        "scenario": scenario.key,
        "retrieved_papers": papers,
        "key_point": "The corpus grows from broad, candidate-specific, and critique-triggered searches.",
    }


def discover_candidates(prompt: str) -> dict[str, Any]:
    scenario = scenario_for_prompt(prompt)
    candidates = [
        {"id": cid, "name": name, "mentions": mentions, "rank_reason": reason}
        for cid, name, mentions, reason in scenario.candidates
    ]
    return {
        "stage": "Candidate discovery",
        "scenario": scenario.key,
        "candidate_funnel": {
            "raw_mentions": 1185,
            "normalized_candidates": 126,
            "after_grounding": 74,
            "after_topic_ranking": 32,
            "verification_queue": len(candidates),
        },
        "verification_queue": candidates,
    }


def verify_candidates(prompt: str) -> dict[str, Any]:
    candidates = discover_candidates(prompt)["verification_queue"]
    labels = ["Confirmed", "Confirmed", "Insufficient Direct Evidence", "Explicit Negative Evidence"]
    verified = []
    for index, candidate in enumerate(candidates):
        label = labels[index]
        if label == "Confirmed":
            state = ["identity supported", "topic context supported", "paper evidence supported"]
        elif label == "Explicit Negative Evidence":
            state = ["identity supported", "exclusion predicate triggered"]
        else:
            state = ["identity supported", "one mandatory predicate unresolved"]
        verified.append({"name": candidate["name"], "label": label, "predicate_state": state})
    return {
        "stage": "Predicate-state verification",
        "verified_rows": verified,
        "key_point": "The decision is controlled by predicate states, not by whether the name sounds plausible.",
    }


def build_run(prompt: str) -> dict[str, Any]:
    refinement = refine(prompt)
    literature = construct_literature(prompt)
    discovery = discover_candidates(prompt)
    verification = verify_candidates(prompt)
    papers = literature["retrieved_papers"]
    candidates = discovery["verification_queue"]
    verified = verification["verified_rows"]
    confirmed = sum(row["label"] == "Confirmed" for row in verified)
    evidence_limited = sum(row["label"] == "Insufficient Direct Evidence" for row in verified)
    excluded = sum(row["label"] == "Explicit Negative Evidence" for row in verified)
    run_candidates = [candidate_detail(candidate, verified[index], papers, index) for index, candidate in enumerate(candidates)]
    return {
        "run_id": f"toy-backend-{uuid.uuid4().hex[:8]}",
        "topic": f"Toy backend run: {refinement['scenario']}",
        "user_request": prompt,
        "refined_definition": refinement["refined_definition"],
        "demo_mode": "backend_toy_run",
        "is_live_run": True,
        "data_notice": "Toy backend run executed on the local FastAPI service. It uses deterministic demo data and does not call external APIs or LLMs.",
        "run_metadata": {
            "mode": "backend_toy_run",
            "is_live_run": True,
            "created_at_unix": time.time(),
            "backend": "FastAPI deterministic toy pipeline",
        },
        "mandatory_predicates": refinement["mandatory_predicates"],
        "exclusion_predicates": refinement["exclusion_predicates"],
        "candidate_funnel": discovery["candidate_funnel"],
        "summary": {
            "literature_records": len(papers),
            "candidate_mentions": discovery["candidate_funnel"]["raw_mentions"],
            "normalized_candidates": discovery["candidate_funnel"]["normalized_candidates"],
            "verification_queue": len(candidates),
            "confirmed": confirmed,
            "evidence_limited": evidence_limited,
            "excluded": excluded,
            "quote_supported_refs": confirmed * 2 + evidence_limited,
        },
        "stages": [
            {"name": "Intent refinement", "state": "complete", "count": len(refinement["mandatory_predicates"]), "note": "Rubric predicates created from user request."},
            {"name": "Dynamic literature construction", "state": "complete", "count": len(papers), "note": "Corpus expanded by broad and follow-up queries."},
            {"name": "Candidate funnel", "state": "complete", "count": len(candidates), "note": "Candidates ranked for verification."},
            {"name": "Predicate-state verification", "state": "complete", "count": len(verified), "note": "Rows assigned evidence-conditioned labels."},
        ],
        "literature": [paper_record(paper, candidates, index) for index, paper in enumerate(papers)],
        "candidates": run_candidates,
    }


def query_for_paper(prompt: str, title: str, trigger: str) -> str:
    terms = re.sub(r"[^a-zA-Z0-9 ]+", " ", prompt).strip().split()[:6]
    title_terms = re.sub(r"[^a-zA-Z0-9 ]+", " ", title).strip().split()[:6]
    return " ".join(terms + title_terms + trigger.split()[:3]).strip()


def paper_record(paper: dict[str, Any], candidates: list[dict[str, Any]], index: int) -> dict[str, Any]:
    used_by = [candidates[0]["id"]]
    if index % 2 == 1 and len(candidates) > 1:
        used_by.append(candidates[1]["id"])
    return {
        "id": paper["id"],
        "title": paper["title"],
        "year": 2020 + index,
        "source": paper["source"],
        "kind": "toy paper record",
        "status": paper["status"],
        "query": paper["query"],
        "triggered_by": paper["triggered_by"],
        "used_by": used_by,
    }


def candidate_detail(candidate: dict[str, Any], verified: dict[str, Any], papers: list[dict[str, Any]], index: int) -> dict[str, Any]:
    label = verified["label"]
    is_confirmed = label == "Confirmed"
    is_negative = label == "Explicit Negative Evidence"
    paper_id = papers[index % len(papers)]["id"]
    benchmark_status = ["benchmark_overlap", "benchmark_missing", "benchmark_overlap", "out_of_scope"][index]
    discovery_type = [
        "benchmark-overlap confirmed entry",
        "benchmark-missing literature-supported entry",
        "benchmark-overlap but evidence-limited under stricter scope",
        "context-only chemical mention",
    ][index]
    if is_confirmed:
        why = f"{candidate['name']} is Confirmed because identity, topic context, and direct evidence predicates are supported in the toy backend run."
        next_action = "No follow-up needed in the toy backend run."
    elif is_negative:
        why = f"{candidate['name']} is Explicit negative because its strongest context triggers an exclusion predicate."
        next_action = "Do not release unless future evidence shows topic-specific product formation."
    else:
        why = f"{candidate['name']} is Evidence-limited because at least one mandatory predicate remains unresolved."
        next_action = "Search for direct evidence supporting the unresolved mandatory predicate."
    final_row = {
        "compound_name": candidate["name"],
        "label": label,
        "benchmark_status": benchmark_status,
        "supporting_papers": [paper_id],
        "why_label": why,
        "next_action": next_action,
    }
    return {
        "id": candidate["id"],
        "name": candidate["name"],
        "synonyms": ["grounded synonym"] if index == 0 else [],
        "formula": "demo-only",
        "label": label,
        "confidence": 0.91 - index * 0.04 if is_confirmed else 0.24 if is_negative else 0.55,
        "mentions": candidate["mentions"],
        "papers": [paper_id],
        "iteration_count": 2 if is_confirmed else 1 if is_negative else 4,
        "benchmark_status": benchmark_status,
        "discovery_type": discovery_type,
        "benchmark_overlap": benchmark_status == "benchmark_overlap",
        "human_release_audit": "accepted" if is_confirmed else "rejected" if is_negative else "needs_more_evidence",
        "triage_reason": candidate["rank_reason"],
        "grounding_status": "normalized identity available",
        "why_label": why,
        "next_action": next_action,
        "final_row": final_row,
        "rubric": [
            {"criterion": "Specific chemical identity", "state": "supported", "evidence": f"{candidate['name']} was normalized as a candidate entity."},
            {"criterion": "Topic-specific context", "state": "contradicted" if is_negative else "supported", "evidence": "The strongest context triggers an exclusion predicate." if is_negative else "The retrieved context is aligned with the requested topic."},
            {"criterion": "Direct evidence requirement", "state": "supported" if is_confirmed else "unresolved", "evidence": "A supporting paper context is available in the toy run." if is_confirmed else "The toy run leaves this item below the Confirmed threshold."},
        ],
        "evidence": [
            {
                "paper": paper_id,
                "quote": f"{candidate['name']} is discussed in topic-specific scientific context." if not is_negative else f"{candidate['name']} appears as a contextual or exclusion-triggering term.",
                "supports": "Exclusion predicate" if is_negative else "Topic and evidence predicates",
                "quality": "explicit_negative" if is_negative else "direct" if is_confirmed else "near_miss",
            }
        ],
        "iterations": [
            {"round": 1, "agent": "Researcher", "action": "retrieve", "result": f"Collected evidence context for {candidate['name']}."},
            {"round": 2, "agent": "Critique", "action": "approve" if is_confirmed else "exclude" if is_negative else "request follow-up", "result": "Required predicates are supported." if is_confirmed else "An exclusion predicate is triggered." if is_negative else "One mandatory predicate remains unresolved."},
        ],
    }


def real_mini_run() -> dict[str, Any]:
    path = DEMO_DIR / "real_mini_run.json"
    return json.loads(path.read_text())
