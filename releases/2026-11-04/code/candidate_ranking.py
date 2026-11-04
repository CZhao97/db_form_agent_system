from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from compound_tool import CompoundDatabaseTool

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - fallback path
    SentenceTransformer = None


EMBED_MODEL_NAME = os.environ.get(
    "CANDIDATE_RANK_EMBED_MODEL",
    "BAAI/bge-small-en-v1.5",
).strip() or "BAAI/bge-small-en-v1.5"


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _normalize_key(value: Any) -> str:
    text = _normalize_text(value).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _candidate_snippet_texts(candidate: dict[str, Any]) -> list[str]:
    snippets: list[str] = []
    seen: set[str] = set()
    for mention in candidate.get("mention_samples") or []:
        text = _normalize_text(mention)
        if " (Context:" in text:
            prefix, remainder = text.split(" (Context:", 1)
            context_text = remainder.strip()
            if context_text.endswith(")"):
                context_text = context_text[:-1].strip()
            text = _normalize_text(context_text or prefix)
        if text and text.casefold() not in seen:
            snippets.append(text)
            seen.add(text.casefold())
    return snippets


def _same_candidate_family(candidate_term: str, matched_name: str) -> bool:
    cand_key = _normalize_key(candidate_term)
    match_key = _normalize_key(matched_name)
    if not cand_key or not match_key:
        return False
    if cand_key == match_key:
        return True
    if len(cand_key) >= 6 and cand_key in match_key:
        return True
    if len(match_key) >= 6 and match_key in cand_key:
        return True
    return False


@lru_cache(maxsize=4096)
def _compound_lookup_payload(term: str) -> dict[str, Any] | None:
    text = _normalize_text(term)
    if not text:
        return None
    try:
        raw = CompoundDatabaseTool()._run(compound_name=text)
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    return payload


def _compound_grounding_score(term: str) -> tuple[float, dict[str, Any] | None]:
    payload = _compound_lookup_payload(term)
    if not payload:
        return 0.0, None

    primary = payload.get("primary") or {}
    synonyms = payload.get("synonyms") or []
    candidates = payload.get("candidates") or []
    norm_term = _normalize_text(term)

    primary_name = _normalize_text(primary.get("name"))
    if primary_name and _normalize_key(primary_name) == _normalize_key(norm_term):
        return 1.0, payload
    if primary_name and _same_candidate_family(norm_term, primary_name):
        return 0.9, payload

    for synonym in synonyms:
        syn_text = _normalize_text(synonym)
        if syn_text and _normalize_key(syn_text) == _normalize_key(norm_term):
            return 0.85, payload
        if syn_text and _same_candidate_family(norm_term, syn_text):
            return 0.75, payload

    for item in candidates:
        if not isinstance(item, dict):
            continue
        candidate_name = _normalize_text(item.get("name"))
        if candidate_name and _normalize_key(candidate_name) == _normalize_key(norm_term):
            return 0.8, payload
        if candidate_name and _same_candidate_family(norm_term, candidate_name):
            return 0.7, payload

    return 0.4, payload


def _candidate_lookup_terms(candidate: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = _normalize_text(value)
        if not text:
            return
        # Mentions may include appended context; keep the entity-like prefix only.
        if " (Context:" in text:
            text = text.split(" (Context:", 1)[0].strip()
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        terms.append(text)

    for key in ("candidate_name", "canonical_name"):
        add(candidate.get(key))
    for syn in candidate.get("entity_synonyms") or []:
        add(syn)
    for mention in candidate.get("mention_samples") or []:
        add(mention)
    return terms


def candidate_surface_forms(candidate: dict[str, Any]) -> list[str]:
    forms: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = _normalize_text(value)
        if not text:
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        forms.append(text)

    add(candidate.get("candidate_name"))
    add(candidate.get("canonical_name"))
    for syn in candidate.get("entity_synonyms") or []:
        add(syn)
    mention_counts = candidate.get("mention_name_counts") or {}
    if isinstance(mention_counts, dict):
        for text in mention_counts:
            add(text)
    return forms


def _topic_definition_text(original_query: str, refined_definition: str | None) -> str:
    if refined_definition and _normalize_text(refined_definition):
        return _normalize_text(refined_definition)
    return _normalize_text(original_query)


@lru_cache(maxsize=1)
def _load_embedder():
    if SentenceTransformer is None:
        return None
    try:
        return SentenceTransformer(EMBED_MODEL_NAME)
    except Exception:
        return None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a_norm = np.linalg.norm(a)
    b_norm = np.linalg.norm(b)
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    return float(np.dot(a, b) / (a_norm * b_norm))


def _semantic_similarity(text: str, topic_texts: list[str]) -> float:
    text = _normalize_text(text)
    topic_texts = [t for t in topic_texts if t]
    if not text or not topic_texts:
        return 0.0

    embedder = _load_embedder()
    if embedder is not None:
        vectors = embedder.encode([text] + topic_texts, normalize_embeddings=True)
        cand_vec = vectors[0]
        topic_vecs = vectors[1:]
        return max(float(np.dot(cand_vec, vec)) for vec in topic_vecs)

    texts = [text] + topic_texts
    tfidf = TfidfVectorizer().fit_transform(texts)
    cand_vec = tfidf[0].toarray()[0]
    topic_vecs = tfidf[1:].toarray()
    return max(_cosine_similarity(cand_vec, vec) for vec in topic_vecs)


def _best_text_similarity(
    candidate_texts: list[str],
    topic_texts: list[str],
) -> tuple[float, str | None, str | None]:
    candidate_texts = [_normalize_text(text) for text in candidate_texts if _normalize_text(text)]
    topic_texts = [_normalize_text(text) for text in topic_texts if _normalize_text(text)]
    if not candidate_texts or not topic_texts:
        return 0.0, None, None

    embedder = _load_embedder()
    best_score = 0.0
    best_candidate_text: str | None = None
    best_topic_text: str | None = None

    if embedder is not None:
        vectors = embedder.encode(candidate_texts + topic_texts, normalize_embeddings=True)
        cand_vecs = vectors[: len(candidate_texts)]
        topic_vecs = vectors[len(candidate_texts) :]
        for cand_idx, cand_vec in enumerate(cand_vecs):
            for topic_idx, topic_vec in enumerate(topic_vecs):
                score = float(np.dot(cand_vec, topic_vec))
                if score > best_score:
                    best_score = score
                    best_candidate_text = candidate_texts[cand_idx]
                    best_topic_text = topic_texts[topic_idx]
        return best_score, best_candidate_text, best_topic_text

    tfidf = TfidfVectorizer().fit_transform(candidate_texts + topic_texts)
    cand_vecs = tfidf[: len(candidate_texts)].toarray()
    topic_vecs = tfidf[len(candidate_texts) :].toarray()
    for cand_idx, cand_vec in enumerate(cand_vecs):
        for topic_idx, topic_vec in enumerate(topic_vecs):
            score = _cosine_similarity(cand_vec, topic_vec)
            if score > best_score:
                best_score = score
                best_candidate_text = candidate_texts[cand_idx]
                best_topic_text = topic_texts[topic_idx]
    return best_score, best_candidate_text, best_topic_text


def _compound_db_match_found(candidate: dict[str, Any]) -> tuple[float, str | None]:
    best_score = 0.0
    best_term: str | None = None
    for term in _candidate_lookup_terms(candidate):
        score, _ = _compound_grounding_score(term)
        if score > best_score:
            best_score = score
            best_term = term
    return best_score, best_term


def rank_candidates_for_topic(
    candidates: list[dict[str, Any]],
    *,
    original_query: str,
    refined_definition: str | None = None,
    verification_query_template: str | None = None,
    top_k: int = 100,
    pubchem_window: int | None = None,
    enable_grounding: bool = True,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    topic_definition = _topic_definition_text(original_query, refined_definition)
    topic_texts = [topic_definition] if topic_definition else []
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        snippet_texts = _candidate_snippet_texts(candidate)
        snippet_score, best_snippet, best_topic_text = _best_text_similarity(snippet_texts, topic_texts)
        snippet_mean = 0.0
        if snippet_texts and topic_texts:
            snippet_scores = [_semantic_similarity(text, topic_texts) for text in snippet_texts]
            if snippet_scores:
                top_scores = sorted(snippet_scores, reverse=True)[: min(3, len(snippet_scores))]
                snippet_mean = float(sum(top_scores) / len(top_scores))
        evidence_score = max(snippet_score, snippet_mean)
        enriched = dict(candidate)
        enriched["topic_similarity_score"] = round(evidence_score, 4)
        enriched["best_snippet_similarity_score"] = round(snippet_score, 4)
        enriched["mean_top_snippet_similarity_score"] = round(snippet_mean, 4)
        enriched["best_name_similarity_score"] = 0.0
        if best_snippet:
            enriched["best_matching_snippet"] = best_snippet
        if best_topic_text:
            enriched["best_matching_topic_text"] = best_topic_text
        best_grounding = 0.0
        if enable_grounding:
            forms = candidate_surface_forms(candidate)
            grounded_forms = []
            for form in forms:
                score, payload = _compound_grounding_score(form)
                if score <= 0.0:
                    continue
                grounded_forms.append(
                    {
                        "form": form,
                        "score": round(score, 4),
                        "primary_name": _normalize_text((payload or {}).get("primary", {}).get("name")),
                    }
                )
                if score > best_grounding:
                    best_grounding = score
            if grounded_forms:
                grounded_forms.sort(key=lambda item: (float(item["score"]), len(item["form"])), reverse=True)
                enriched["grounded_surface_forms"] = grounded_forms[:5]
        enriched["grounding_score"] = round(best_grounding, 4)
        ranked.append(enriched)

    ranked.sort(
        key=lambda item: (
            float(item.get("topic_similarity_score") or 0.0),
            float(item.get("grounding_score") or 0.0),
            int(item.get("mention_count") or 0),
        ),
        reverse=True,
    )

    if enable_grounding:
        if pubchem_window is None:
            pubchem_window = min(max(top_k // 2, 25), 75)

        for candidate in ranked[:pubchem_window]:
            compound_score, matched_term = _compound_db_match_found(candidate)
            candidate["compound_match_score"] = round(compound_score, 4)
            if matched_term:
                candidate["compound_match_term"] = matched_term
            candidate["pre_rank_score"] = float(
                0.8 * float(candidate["topic_similarity_score"]) + 0.2 * float(candidate.get("grounding_score") or 0.0)
            )

        for candidate in ranked[pubchem_window:]:
            candidate["compound_match_score"] = 0.0
            candidate["pre_rank_score"] = float(
                0.8 * float(candidate["topic_similarity_score"]) + 0.2 * float(candidate.get("grounding_score") or 0.0)
            )
    else:
        for candidate in ranked:
            candidate["compound_match_score"] = 0.0
            candidate["pre_rank_score"] = float(candidate["topic_similarity_score"])

    ranked.sort(
        key=lambda item: (
            float(item.get("topic_similarity_score") or 0.0),
            float(item.get("grounding_score") or 0.0),
            float(item.get("compound_match_score") or 0.0),
            float(item.get("pre_rank_score") or 0.0),
            int(item.get("mention_count") or 0),
        ),
        reverse=True,
    )
    return ranked[: max(int(top_k), 0)]
