"""Executable decision contract for new runs, independent of agent agreement.

Evidence directions are model assessments. Citation checks establish source
binding, not scientific truth. Historical files are never rewritten here.
"""
import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path

VERSION = "decision-contract-20261020-binding-v6"
STATES = {"supported", "contradicted", "unresolved", "conflicting"}


def unwrap(payload):
    if not isinstance(payload, dict):
        return {}
    return payload.get("critique", payload)


def criterion_items(payload):
    payload = unwrap(payload)
    for obj, key in ((payload, "checklist"), (payload.get("rubric", {}), "criteria"),
                     (payload.get("criteria_assessment", {}), "items")):
        if isinstance(obj, dict) and isinstance(obj.get(key), list):
            return obj[key]
    return []


def name(item):
    return str(item.get("name") or item.get("item") or "").strip()


def assess_conditions(payload, expected=None):
    """Require directional support, complete input coverage, and explicit ANY.

    A negative-worded inclusion (e.g. 'excludes formulations') is supported
    when satisfied. Only explicitly declared exclusion-trigger propositions
    use the opposite direction. No keyword-based polarity inference is used.
    """
    items = criterion_items(payload)
    specs = expected if expected is not None else items
    problems = []
    if not specs or not items:
        return False, ["missing_criterion_assessment"]
    if not any(item.get("priority", "mandatory") != "optional" for item in specs):
        return False, ["no_required_conditions"]
    by_name = {name(item): item for item in items if isinstance(item, dict)}
    if len(by_name) != len(items) or "" in by_name:
        return False, ["duplicate_or_invalid_criterion"]
    if any(not isinstance(item, dict) or not name(item) for item in specs):
        return False, ["invalid_frozen_contract"]
    for spec in specs:
        key = name(spec)
        item = by_name.get(key)
        priority = str(spec.get("priority", "mandatory")).lower()
        if priority == "optional":
            continue
        if item is None:
            problems.append(key + ": omitted")
            continue
        state = item.get("evidence_state")
        if state not in STATES:
            problems.append(key + ": missing_direction")
            continue
        if spec.get("operator") == "ANY":
            alternatives = spec.get("alternatives", [])
            selected = item.get("supported_alternative")
            if not alternatives or selected not in alternatives:
                problems.append(key + ": unbound_ANY_alternative")
        required = "contradicted" if spec.get("polarity") == "exclusion_trigger" else "supported"
        if state != required:
            problems.append(key + ": " + state)
        if not isinstance(item.get("evidence_ids"), list) or not item["evidence_ids"]:
            problems.append(key + ": missing_evidence_links")
    if set(by_name) != {name(spec) for spec in specs}:
        problems.append("criterion_set_differs_from_frozen_input")
    return not problems, problems


def adjudicate(researcher_claim, critique_decision, stop_reason, agreement_status=None,
               critique_claim=None, critique_payload=None, expected=None):
    """Return one terminal label and provisional eligibility before source checks."""
    proposed = str(critique_claim or researcher_claim or "Insufficient Direct Evidence").strip()
    reason = str(stop_reason or "").upper()
    if reason in {"TIMEOUT", "ERROR", "TOOL_UNAVAILABLE"}:
        return "Insufficient Direct Evidence", False, "technical_" + reason.lower()
    if proposed != "Confirmed":
        return proposed, False, "not_confirmed"
    okay, problems = assess_conditions(critique_payload, expected)
    if str(critique_decision or "").lower() != "approve" or not okay:
        return "Insufficient Direct Evidence", False, "contract_unresolved:" + "|".join(problems)
    return "Confirmed", True, "directional_contract_satisfied_pending_source_audit"


def normalize_text(value):
    text = unicodedata.normalize("NFKC", str(value))
    text = text.translate(str.maketrans({"\u00ad": "", "\u200b": "", "\ufeff": "",
        "\u2010": "-", "\u2011": "-", "\u2013": "-", "\u2014": "-",
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}))
    return " ".join(text.split())


def quote_located(quote, text):
    quote, text = normalize_text(quote), normalize_text(text)
    if not quote:
        return False
    if quote in text:
        return True
    # Only an explicit omission marker permits discontinuous quoted excerpts.
    parts = [part.strip() for part in re.split(r"\.{3,}", quote) if part.strip()]
    if len(parts) < 2 or any(len(part) < 20 for part in parts):
        return False
    end = 0
    for part in parts:
        start = text.find(part, end)
        if start < 0:
            return False
        end = start + len(part)
    return True


def identity_key(value):
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "pmid:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def title_key(value):
    return " ".join("".join(c if c.isalnum() else " " for c in
                           unicodedata.normalize("NFKC", str(value or "")).casefold()).split())


def registry_from_session(session_dir, evidence):
    """Resolve against retrieved paper JSON, never model-generated result JSON."""
    if not session_dir or not Path(session_dir).is_dir():
        return {}
    docs = []
    for path in Path(session_dir).rglob("*.json"):
        if path.name in {"rubric_eval.json", "result.json", "task.json"}:
            continue
        try:
            doc = json.loads(path.read_text())
        except (ValueError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(doc, dict) or not doc.get("title"):
            continue
        if not isinstance(doc.get("full_text") or doc.get("abstract"), str):
            continue
        ids = doc.get("ids") or {}
        keys = {identity_key(doc.get(k) or ids.get(k)) for k in ("doi", "pmid", "pmcid")}
        docs.append((doc, keys - {""}, path))
    registry = {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or item.get("source_id") or "")
        wanted = {identity_key(item.get(k)) for k in ("doi", "pmid", "pmcid", "doi_or_pmid")} - {""}
        title = title_key(item.get("title") or item.get("source_title"))
        matches = [(doc, path) for doc, keys, path in docs
                   if (not wanted or wanted <= keys) and title and title == title_key(doc["title"])]
        # Full text and abstract snapshots of the same identified paper are
        # complementary versions, not competing source identities.
        if not wanted:
            identities = {tuple(sorted(identity_key(doc.get(k) or (doc.get("ids") or {}).get(k))
                                       for k in ("doi", "pmid", "pmcid"))) for doc, _ in matches}
            if len(identities) > 1:
                continue
        unique = {}
        for doc, path in matches:
            text = doc.get("full_text") or doc.get("abstract")
            unique.setdefault(hashlib.sha256(text.encode()).hexdigest(), (doc, path))
        if not unique:
            continue
        versions = list(unique.values())
        doc, path = max(versions, key=lambda pair: len(pair[0].get("full_text") or pair[0].get("abstract")))
        registry[sid] = dict(text=doc.get("full_text") or doc.get("abstract"),
            source_texts=[d[key] for d, _ in versions for key in ("full_text", "abstract")
                          if isinstance(d.get(key), str) and d[key]],
            source_versions=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                             for _, p in versions],
            source_type="paper", metadata_verified=True, source_path=str(path),
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            retrieved_title=doc["title"], retracted=any(d.get("retracted") is True for d, _ in versions))
    return registry


def verify_all_citations(evidence, registry):
    """Check every supplied paper record and every attributed quote.

    registry is constructed by the retrieval/audit code, not model output.
    Native database/tool records are separate and never paper support.
    """
    issues, paper_ids, seen = [], set(), set()
    if not isinstance(evidence, list) or not isinstance(registry, dict):
        return False, ["invalid_evidence_or_registry"], set()
    for item in evidence:
        if not isinstance(item, dict):
            issues.append("invalid_reference_record")
            continue
        sid = str(item.get("id") or item.get("source_id") or "")
        if not sid or sid in seen:
            issues.append(sid + ": missing_or_duplicate_id")
        seen.add(sid)
        source = registry.get(sid)
        if not isinstance(source, dict):
            issues.append(sid + ": source_not_bound")
            continue
        # Source type must come from the trusted registry, not the proposed row.
        if source.get("source_type") in {"compound_database", "tool"}:
            if source.get("metadata_verified") is not True or source.get("tool_receipt_bound") is not True:
                issues.append(sid + ": tool_record_not_bound")
            continue
        paper_ids.add(sid)
        if source.get("metadata_verified") is not True:
            issues.append(sid + ": metadata_not_verified")
        if source.get("retracted") is True:
            issues.append(sid + ": retraction_requires_adjudication")
        texts = [normalize_text(text) for text in source.get("source_texts", [source.get("text", "")])]
        quotes = item.get("quotes")
        if quotes is None:
            quotes = [item.get("quote") or item.get("snippet") or ""]
        if not isinstance(quotes, list) or not quotes:
            issues.append(sid + ": missing_attributed_span")
            continue
        for quote in quotes:
            if isinstance(quote, dict):
                quote = quote.get("quote") or quote.get("snippet") or quote.get("text") or ""
            quote = normalize_text(quote)
            if not any(quote_located(quote, text) for text in texts if text):
                issues.append(sid + ": attributed_span_not_located")
    if not paper_ids:
        issues.append("no_primary_paper_evidence")
    return not issues, issues, paper_ids


def finalize(report, expected, registry):
    """Bind final label, accepted and release_eligible to one decision record."""
    out = copy.deepcopy(report)
    raw = {k: out.get(k) for k in ("claim", "researcher_claim", "critique_claim",
                                  "accepted", "final_adjudicated_claim")}
    payload = out.get("criterion_assessment") or {"rubric": out.get("rubric", {})}
    label, okay, reason = adjudicate(
        out.get("researcher_claim") or out.get("claim"),
        out.get("critique_decision"), out.get("stop_reason"),
        out.get("agreement_status"), out.get("critique_claim"),
        payload, expected)
    references_ok, issues, paper_ids = verify_all_citations(out.get("evidence", []), registry)
    if out.get("final_report_bound_to_critique") is False:
        issues.append("final_report_not_bound_to_critique")
    # Identity records may support identity, but never enter the paper denominator.
    # Their semantic role is assessed under the unchanged scientific rubric.
    identity_ids = set()
    for position, item in enumerate(out.get("identity_records") or [], 1):
        sid = str(item.get("id") or f"Identity Record {position}")
        source = registry.get(sid, {})
        if (source.get("source_type") == "compound_database"
                and source.get("metadata_verified") is True and source.get("tool_receipt_bound") is True):
            identity_ids.add(sid)
        else:
            issues.append(sid + ": identity_record_not_bound_to_tool_receipt")
    tool_ids = {str(item.get("id") or item.get("source_id") or "") for item in out.get("evidence", [])
                if isinstance(item, dict) and registry.get(str(item.get("id") or item.get("source_id") or ""), {}).get("tool_receipt_bound") is True}
    linked_ids = paper_ids | identity_ids | tool_ids
    priorities = {name(spec): spec.get("priority", "mandatory") for spec in expected}
    for item in criterion_items(payload):
        if priorities.get(name(item)) == "optional":
            continue
        if not set(item.get("evidence_ids") or []) <= linked_ids:
            issues.append(name(item) + ": criterion_link_not_in_verified_evidence")
    eligible = okay and references_ok and not issues
    if label == "Confirmed" and not eligible:
        label = "Insufficient Direct Evidence"
    out.update(claim=label, final_adjudicated_claim=label, accepted=eligible,
               release_eligible=eligible, decision_policy_version=VERSION,
               proposed_decisions=raw, release_check_status="checked",
               release_check_reason=reason, citation_audit_issues=issues,
               all_paper_citations_verified=references_ok,
               contract_sha256=hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest())
    out["decision_record_id"] = hashlib.sha256(json.dumps(
        {"contract": out["contract_sha256"], "label": label, "accepted": eligible,
         "evidence": out.get("evidence"), "criteria": payload}, sort_keys=True).encode()).hexdigest()
    return out
