import json
import os
from typing import Any
from pathlib import Path


def _parse_json_if_possible(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except Exception:
        return value


def _to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2)

def build_default_search_budget() -> dict[str, Any]:
    return {
        "batch1_max_search_directions": 3,
        "batch1_max_identity_terms": 2,
        "batch1_max_primary_context_terms": 2,
        "defer_method_fanout_until_followup": True,
        "avoid_near_duplicate_context_terms": True,
    }


def _normalize_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_context_items(values: Any, limit: int = 5) -> list[dict[str, str]]:
    if not isinstance(values, list):
        return []
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        if isinstance(value, str):
            item = {"mention": "", "context": value.strip()}
        elif isinstance(value, dict):
            item = {
                "mention": str(value.get("mention") or "").strip(),
                "context": str(value.get("context") or "").strip(),
                "source": str(value.get("source") or "").strip(),
            }
        else:
            continue
        context = item.get("context", "")
        mention = item.get("mention", "")
        if not context and not mention:
            continue
        key = (mention.casefold(), context.casefold())
        if key in seen:
            continue
        seen.add(key)
        compact = {k: v for k, v in item.items() if v}
        normalized.append(compact)
        if len(normalized) >= limit:
            break
    return normalized


def _normalize_middle_entity_data(entity_data: Any) -> list[dict[str, Any]]:
    if not isinstance(entity_data, list):
        return []

    normalized_entities: list[dict[str, Any]] = []
    for entity in entity_data:
        if not isinstance(entity, dict):
            continue
        entity_id = str(entity.get("id") or entity.get("entity_id") or "").strip()
        if not entity_id:
            continue
        names = _normalize_string_list(entity.get("names"))
        if not names:
            continue
        normalized_entity: dict[str, Any] = {
            "id": entity_id,
            "names": names,
        }
        mention_contexts = _normalize_context_items(entity.get("mention_contexts"))
        if mention_contexts:
            normalized_entity["mention_contexts"] = mention_contexts
        normalized_entities.append(normalized_entity)
    return normalized_entities


def build_refinement_request(user_query: str) -> str:
    return _to_json({
        "task": "refine_topic_definition",
        "user_query": user_query,
    })


def build_definition_confirmation_payload() -> str:
    return _to_json({
        "task": "confirm_definition",
        "status": "confirmed",
    })


def build_upper_stream_request(original_query: str, refined_definition: str | None = None) -> str:
    payload: dict[str, Any] = {
        "task": "search_literature_for_candidate_chemicals",
        "original_query": original_query,
    }
    if refined_definition:
        payload["refined_definition"] = refined_definition
    return _to_json(payload)


def build_query_generator_input(
    original_query: str,
    entity_data: list[dict[str, Any]],
    refined_definition: str | None = None,
    verification_query_template: str | None = None,
    evaluation_criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task": "filter_candidate_entities",
        "original_query": original_query,
        "middle_stage_mode": "context_aware_entity_triage",
        "entity_data": _normalize_middle_entity_data(entity_data),
    }
    if refined_definition:
        payload["refined_definition"] = refined_definition
    if verification_query_template:
        payload["verification_query_template"] = verification_query_template
    # NEW: Pass structured evaluation criteria if available
    if evaluation_criteria:
        payload["evaluation_criteria"] = evaluation_criteria
    return payload


def _criteria_sections_from_input(criteria_input: Any) -> dict[str, list[str]]:
    def _normalize_section_key(key: str) -> str:
        lowered = str(key).strip().casefold().rstrip(":")
        aliases = {
            "criteria": "criteria",
            "criterion": "criteria",
            "evidence requirements": "evidence requirements",
            "evidence": "evidence requirements",
            "exclusions": "exclusions",
            "scope": "scope",
        }
        return aliases.get(lowered, lowered)

    parsed = _parse_json_if_possible(criteria_input)
    if isinstance(parsed, dict):
        eval_criteria = parsed.get("evaluation_criteria")
        if isinstance(eval_criteria, dict):
            return _criteria_sections_from_input(eval_criteria)
        final_definition = parsed.get("final_definition")
        if isinstance(final_definition, str) and final_definition.strip():
            return _criteria_sections_from_input(final_definition.strip())
        out: dict[str, list[str]] = {}
        for key, value in parsed.items():
            if str(key).strip().casefold() in {"rubric_items", "verification_query_template", "final_definition"}:
                continue
            normalized_key = _normalize_section_key(str(key))
            if isinstance(value, str) and value.strip():
                out[normalized_key] = [value.strip()]
            elif isinstance(value, list):
                items = [str(item).strip() for item in value if str(item).strip()]
                if items:
                    out[normalized_key] = items
        if out:
            return out

    if not isinstance(criteria_input, str):
        return {}

    text = criteria_input.strip()
    if not text:
        return {}

    sections: dict[str, list[str]] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = line.lstrip("*-• ").strip()
        if not line:
            continue
        lower = line.casefold()
        matched_section = None
        for prefix in ("criteria:", "criterion:", "evidence requirements:", "evidence:", "exclusions:", "scope:"):
            if lower.startswith(prefix):
                matched_section = _normalize_section_key(prefix)
                remainder = line[len(prefix):].strip()
                current_key = matched_section
                sections.setdefault(current_key, [])
                if remainder:
                    sections[current_key].append(remainder)
                break
        if matched_section:
            continue
        if current_key:
            sections.setdefault(current_key, []).append(line)

    return {k: v for k, v in sections.items() if v}


def _criteria_text_from_input(criteria_input: Any) -> str:
    parsed = _parse_json_if_possible(criteria_input)
    if isinstance(parsed, dict):
        final_definition = parsed.get("final_definition")
        if isinstance(final_definition, str) and final_definition.strip():
            sections = _criteria_sections_from_input(final_definition)
            if sections:
                return _criteria_text_from_input(final_definition)
            return final_definition.strip()
    sections = _criteria_sections_from_input(criteria_input)
    if sections:
        ordered_keys = ["criteria", "criterion", "evidence requirements", "evidence", "exclusions", "scope"]
        rendered: list[str] = []
        seen: set[str] = set()
        for key in ordered_keys + [k for k in sections.keys() if k not in ordered_keys]:
            if key in seen or key not in sections:
                continue
            seen.add(key)
            label = key.title()
            rendered.append(f"{label}:")
            rendered.extend(f"- {item}" for item in sections[key])
        return "\n".join(rendered)
    if isinstance(criteria_input, str):
        return criteria_input.strip()
    return ""


def extract_verification_query_template(criteria_input: Any) -> str:
    parsed = _parse_json_if_possible(criteria_input)
    if isinstance(parsed, dict):
        eval_criteria = parsed.get("evaluation_criteria")
        if isinstance(eval_criteria, dict):
            return extract_verification_query_template(eval_criteria)
        raw_template = parsed.get("verification_query_template")
        if isinstance(raw_template, str) and raw_template.strip():
            return raw_template.strip()
        final_definition = parsed.get("final_definition")
        if isinstance(final_definition, str) and final_definition.strip():
            return extract_verification_query_template(final_definition)
    return ""


def materialize_verification_query(entity_name: str, template: str | None, fallback_query: str | None) -> str:
    entity = str(entity_name or "").strip()
    raw_template = str(template or "").strip()
    if raw_template and "{{CANDIDATE}}" in raw_template and entity:
        return raw_template.replace("{{CANDIDATE}}", entity)
    if raw_template:
        return raw_template
    return str(fallback_query or entity).strip()


def extract_rubric_items(criteria_text: Any) -> list[dict[str, str]]:
    def tagged_item(value: str, default_priority: str = "mandatory") -> dict:
        text = str(value).strip().lstrip("-* ").strip()
        priority = default_priority
        for marker, kind in (("[mandatory]", "mandatory"), ("[optional]", "optional")):
            if text.casefold().startswith(marker):
                text, priority = text[len(marker):].strip(), kind
                break
        return {"name": text, "priority": priority, "section": "criteria"}

    parsed = _parse_json_if_possible(criteria_text)
    if isinstance(parsed, dict):
        eval_criteria = parsed.get("evaluation_criteria")
        if isinstance(eval_criteria, dict):
            return extract_rubric_items(eval_criteria)
        final_definition = parsed.get("final_definition")
        raw_items = parsed.get("rubric_items")
        if isinstance(raw_items, list):
            normalized_items: list[dict[str, str]] = []
            seen: set[tuple[str, str, str]] = set()
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("item") or "").strip()
                if not name:
                    continue
                section = str(item.get("section") or "").strip().lower() or "criteria"
                if section in {"criteria_text", "fixed_criteria"}:
                    # These are serialized field wrappers from old exports,
                    # not user-declared optional scientific conditions.
                    continue
                priority = str(item.get("priority") or "").strip().lower() or ("mandatory" if section in {"criteria", "criterion", "exclusions"} else "optional")
                key = (name.casefold(), section, priority)
                if key in seen:
                    continue
                seen.add(key)
                normalized_items.append({
                    "name": name,
                    "section": section,
                    "priority": "mandatory" if priority == "mandatory" else "optional",
                    **{k: item[k] for k in ("id", "operator", "alternatives", "polarity")
                       if k in item},
                })
            if normalized_items:
                return normalized_items
        # Explicit legacy fields must not fall through as arbitrary optional
        # section names when the structured list exists but is empty.
        text = parsed.get("criteria_text")
        if isinstance(text, str):
            lines = [line.strip().lstrip("-* ").strip() for line in text.splitlines() if line.strip()]
            if lines and all(line.casefold().startswith(("[mandatory]", "[optional]")) for line in lines):
                return [tagged_item(line) for line in lines]
        fixed = parsed.get("fixed_criteria")
        if isinstance(fixed, list) and fixed and all(isinstance(item, str) and item.strip() for item in fixed):
            return [tagged_item(item) for item in fixed]
        if isinstance(final_definition, str) and final_definition.strip():
            return extract_rubric_items(final_definition.strip())

    sections = _criteria_sections_from_input(criteria_text)
    if not sections:
        return []

    ordered_keys = ["criteria", "evidence requirements", "exclusions", "scope"]
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key in ordered_keys + [k for k in sections.keys() if k not in ordered_keys]:
        for item in sections.get(key, []):
            name = str(item).strip()
            if not name:
                continue
            normalized_section = key
            priority = "mandatory" if normalized_section in {"criteria", "criterion", "exclusions"} else "optional"
            dedupe_key = (name.casefold(), normalized_section)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            items.append({
                "name": name,
                "section": normalized_section,
                "priority": priority,
            })
    return items


def build_verification_task_payload(
    entity_name: str,
    original_query: str,
    refined_definition: str | None = None,
    entity_id: str | None = None,
    entity_synonyms: list[str] | None = None,
    seed_sources: list[dict[str, Any]] | None = None,
    seed_source_brief: list[dict[str, Any]] | None = None,
    relevance_score: float | None = None,
    domain: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "task": "verify_candidate_entity",
        "entity_name": entity_name,
        "original_query": original_query,
    }
    if refined_definition:
        refined_text = _criteria_text_from_input(refined_definition)
        rubric_items = extract_rubric_items(refined_definition)
        fixed_criteria = [item["name"] for item in rubric_items if item.get("priority") == "mandatory"] or extract_fixed_criteria_key_points(refined_definition)
        payload["evaluation_criteria"] = {
            "criteria_text": refined_text or refined_definition,
            "rubric_items": rubric_items,
            "fixed_criteria": fixed_criteria,
        }
    if entity_id:
        payload["entity_id"] = entity_id
    normalized_synonyms = _normalize_string_list(entity_synonyms)
    if normalized_synonyms:
        payload["entity_synonyms"] = normalized_synonyms
    if isinstance(seed_sources, list):
        normalized_sources: list[dict[str, Any]] = []
        for source in seed_sources:
            if not isinstance(source, dict):
                continue
            normalized_source: dict[str, Any] = {}
            for key in ("title", "doi", "local_pdf_path", "url", "notes"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    normalized_source[key] = value.strip()
            if normalized_source:
                normalized_sources.append(normalized_source)
        if normalized_sources:
            payload["seed_sources"] = normalized_sources
    if isinstance(seed_source_brief, list):
        normalized_brief: list[dict[str, Any]] = []
        for item in seed_source_brief:
            if not isinstance(item, dict):
                continue
            normalized_item: dict[str, Any] = {}
            for key in ("title", "doi", "quote", "why_relevant"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    normalized_item[key] = value.strip()
            if normalized_item:
                normalized_brief.append(normalized_item)
        if normalized_brief:
            payload["seed_source_brief"] = normalized_brief
    if relevance_score is not None:
        try:
            payload["relevance_score"] = float(relevance_score)
        except (TypeError, ValueError):
            pass
    if domain:
        payload["domain"] = domain
    payload.setdefault("search_budget", build_default_search_budget())
    return _to_json(payload)


def build_researcher_fallback_payload() -> str:
    return _to_json({
        "synthesis": {
            "claim": "Insufficient Direct Evidence",
            "explanation": "internal_error",
            "limitations": "empty_response",
        },
        "traceability": {},
        "next_actions": {},
    })


def build_critique_auto_approval_payload() -> str:
    return _to_json({
        "critique": {
            "decision": "APPROVE",
            "rubric": {"overall_score": 1.0, "criteria": []},
            "explanation": "ablation_auto_approve",
        },
        "supporting_sources": [],
        "stop_reason": "APPROVED",
    })


def extract_criteria_text(original_query: Any) -> str:
    parsed = _parse_json_if_possible(original_query)
    if isinstance(parsed, dict):
        eval_criteria = parsed.get("evaluation_criteria")
        if isinstance(eval_criteria, dict):
            eval_text = _criteria_text_from_input(eval_criteria.get("criteria_text"))
            if eval_text:
                return eval_text
        for key in ("refined_definition", "criteria", "definition"):
            value = parsed.get(key)
            text = _criteria_text_from_input(value)
            if text:
                return text
        original = parsed.get("original_query")
        if isinstance(original, str) and original.strip():
            return original.strip()

    if not original_query or not isinstance(original_query, str):
        return ""

    markers = ["Refined Definition/Criteria:", "Refined Definition:", "Definition:"]
    for marker in markers:
        idx = original_query.find(marker)
        if idx != -1:
            return original_query[idx + len(marker):].strip()
    return original_query.strip()


def extract_criteria_key_points(criteria_text: Any) -> list[str]:
    text = _criteria_text_from_input(criteria_text)
    if not text:
        return []

    section_prefixes = {
        "criteria:": "criteria",
        "criterion:": "criteria",
        "evidence requirements:": "evidence_requirements",
        "evidence:": "evidence_requirements",
        "exclusions:": "exclusions",
        "scope:": "scope",
    }

    key_points: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = line.lstrip("-*• ")
        line = line.strip()
        if not line:
            continue

        lower_full = line.casefold()
        lower = lower_full.rstrip(":")
        if lower in {
            "final definition",
            "rubric",
            "refined definition",
            "refined definition/criteria",
            "criteria",
            "criterion",
            "exclusions",
            "scope",
            "evidence requirements",
            "evidence",
        }:
            continue

        matched_prefix = None
        for prefix in section_prefixes:
            if lower_full.startswith(prefix):
                matched_prefix = prefix
                break

        if matched_prefix:
            remainder = line[len(matched_prefix):].strip()
            if not remainder:
                continue
            line = remainder

        # Skip obvious non-criteria metadata lines.
        if line.lower().startswith(("please confirm", "confirm or adjust", "verification query template")):
            continue

        # Skip placeholder/header-like lines that are too short to be judgeable.
        if len(line.split()) < 4 and not any(ch.isdigit() for ch in line):
            continue

        key_points.append(line)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in key_points:
        normalized = item.casefold()
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(item)
    return deduped


def extract_fixed_criteria_key_points(criteria_text: Any) -> list[str]:
    if isinstance(criteria_text, dict):
        evaluation_criteria = criteria_text.get("evaluation_criteria")
        if isinstance(evaluation_criteria, dict):
            raw_key_points = evaluation_criteria.get("criteria_key_points")
            normalized_key_points = _normalize_string_list(raw_key_points)
            if normalized_key_points:
                return normalized_key_points
        raw_key_points = criteria_text.get("criteria_key_points")
        normalized_key_points = _normalize_string_list(raw_key_points)
        if normalized_key_points:
            return normalized_key_points
    sections = _criteria_sections_from_input(criteria_text)
    if sections:
        prioritized: list[str] = []
        # Keep the downstream checklist focused on core positive criteria.
        # Evidence requirements remain available in the full rubric text, but
        # should not automatically become hard veto items unless no explicit
        # core-criteria section exists.
        for key in ("criteria", "criterion"):
            prioritized.extend(sections.get(key, []))
        if not prioritized:
            for key in ("evidence requirements", "evidence"):
                prioritized.extend(sections.get(key, []))
        deduped: list[str] = []
        seen: set[str] = set()
        for item in prioritized:
            normalized = item.casefold()
            if normalized not in seen:
                seen.add(normalized)
                deduped.append(item)
        if deduped:
            return deduped
    return extract_criteria_key_points(criteria_text)


def extract_next_queries_from_critique(critique_json: Any) -> list[str]:
    critique_obj = _parse_json_if_possible(critique_json)
    if not isinstance(critique_obj, dict):
        return []

    critique_section = critique_obj.get("critique")
    if not isinstance(critique_section, dict):
        return []

    next_queries: list[str] = []
    raw_next = critique_section.get("next_query")
    if isinstance(raw_next, str) and raw_next.strip():
        next_queries.append(raw_next.strip())
    elif isinstance(raw_next, list):
        next_queries.extend(str(item).strip() for item in raw_next if str(item).strip())

    checklist = critique_section.get("checklist")
    if isinstance(checklist, list):
        for item in checklist:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status == "solved":
                continue
            follow_up = item.get("follow_up_queries")
            if isinstance(follow_up, str) and follow_up.strip():
                next_queries.append(follow_up.strip())
            elif isinstance(follow_up, list):
                next_queries.extend(str(entry).strip() for entry in follow_up if str(entry).strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for query in next_queries:
        if query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


def extract_unsolved_checklist_items(critique_json: Any) -> list[dict[str, Any]]:
    critique_obj = _parse_json_if_possible(critique_json)
    if not isinstance(critique_obj, dict):
        return []
    critique_section = critique_obj.get("critique")
    if not isinstance(critique_section, dict):
        return []
    checklist = critique_section.get("checklist")
    if not isinstance(checklist, list):
        return []

    unsolved: list[dict[str, Any]] = []
    for item in checklist:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status and status != "solved":
            unsolved.append(item)
    return unsolved


def _count_solved_items(obj: Any) -> int:
    if not isinstance(obj, dict):
        return 0
    solved_items = obj.get("solved_items")
    if isinstance(solved_items, list):
        count = sum(1 for item in solved_items if str(item).strip())
        if count:
            return count
    criteria_assessment = obj.get("criteria_assessment")
    if isinstance(criteria_assessment, dict):
        items = criteria_assessment.get("items")
        if isinstance(items, list):
            return sum(1 for item in items if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "solved")
    checklist = obj.get("checklist")
    if isinstance(checklist, list):
        return sum(1 for item in checklist if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "solved")
    return 0


def build_researcher_followup_payload(
    current_task: str,
    previous_researcher_json: str,
    review_feedback_json: str,
) -> str:
    previous_researcher_obj = _parse_json_if_possible(previous_researcher_json)
    review_feedback_obj = _parse_json_if_possible(review_feedback_json)
    payload: dict[str, Any] = {
        "task": "continue_verification",
        "current_task": _parse_json_if_possible(current_task),
        "previous_researcher_output": previous_researcher_obj,
        "review_feedback": review_feedback_obj,
    }
    previous_solved_count = _count_solved_items(previous_researcher_obj)
    critique_solved_count = _count_solved_items(review_feedback_obj.get("critique") if isinstance(review_feedback_obj, dict) else None)
    payload["rubric_progress"] = {
        "previous_researcher_solved_count": previous_solved_count,
        "current_reference_solved_count": critique_solved_count,
        "solved_count_delta": critique_solved_count - previous_solved_count,
    }
    unsolved = extract_unsolved_checklist_items(review_feedback_json)
    if unsolved:
        payload["unsolved_checklist_items"] = unsolved
    next_queries = extract_next_queries_from_critique(review_feedback_json)
    if next_queries:
        payload["follow_up_queries"] = next_queries
    return _to_json(payload)


def build_critique_request_payload(
    criteria_text: str,
    researcher_output_json: str,
    current_task: str | None = None,
    previous_critique_json: str | None = None,
) -> str:
    rubric_source: Any = current_task if current_task else criteria_text
    rubric_items = extract_rubric_items(rubric_source)
    criteria_key_points = extract_fixed_criteria_key_points(rubric_source)
    fixed_criteria = [item["name"] for item in rubric_items if item.get("priority") == "mandatory"] or criteria_key_points
    payload: dict[str, Any] = {
        "task": "critique_research_output",
        "criteria": _criteria_text_from_input(criteria_text) or criteria_text,
        "rubric_items": rubric_items,
        "fixed_criteria": fixed_criteria,
        "criteria_key_points": criteria_key_points,
        "researcher_output": _parse_json_if_possible(researcher_output_json),
    }
    if current_task:
        parsed_task = _parse_json_if_possible(current_task)
        if isinstance(parsed_task, dict):
            slim_task: dict[str, Any] = {}
            target_name = parsed_task.get("entity_name")
            if isinstance(target_name, str) and target_name.strip():
                clean_name = target_name.strip()
                payload["target_entity_name"] = clean_name
                slim_task["entity_name"] = clean_name
            domain = parsed_task.get("domain")
            if isinstance(domain, str) and domain.strip():
                slim_task["domain"] = domain.strip()
            target_synonyms = _normalize_string_list(parsed_task.get("entity_synonyms"))
            if target_synonyms:
                payload["target_entity_synonyms"] = target_synonyms
                slim_task["entity_synonyms"] = target_synonyms
            if slim_task:
                payload["current_task"] = slim_task
        else:
            payload["current_task"] = parsed_task
    if previous_critique_json:
        payload["previous_critique"] = _parse_json_if_possible(previous_critique_json)
    return _to_json(payload)





def create_evaluation_criteria_from_definition(
    user_definition: str,
    domain: str = "dbp",
    cache_file: Path | str | None = None,
) -> dict[str, Any]:
    """
    Load evaluation criteria from cache file.
    The actual refinement agent call should happen at the orchestrator level (e.g., in run_dbcurator_section1_eval.py).
    
    Args:
        user_definition: The raw user-provided definition (for fallback only)
        domain: The domain (dbp, blood_exposome, etc.)
        cache_file: Path to load the pre-generated refined rubric from
        
    Returns:
        dict with keys: criteria_text, rubric_items, fixed_criteria, verification_query_template
    """
    # Try to load from cache file if provided
    if cache_file:
        cache_path = Path(cache_file)
        if cache_path.exists():
            try:
                with open(cache_path) as f:
                    cached = json.load(f)
                    if "rubric_items" in cached:
                        return cached
            except Exception as e:
                print(f"Warning: Failed to load cache from {cache_path}: {e}")
    
    # Fallback: Return a basic structure if no cache available
    print(f"Warning: No cached rubric found. Using fallback structure.")
    return {
        "criteria_text": user_definition,
        "rubric_items": [
            {
                "name": user_definition,
                "section": "rubric",
                "priority": "mandatory"
            }
        ],
        "fixed_criteria": [user_definition],
        "verification_query_template": f"Decide whether '{{{{CANDIDATE}}}}' satisfies the {domain} definition."
    }
