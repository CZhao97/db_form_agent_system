#!/usr/bin#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Full-text literature fetcher (PubMed/PMC + preprints) with Europe PMC + Unpaywall.
- PubMed search biased to "Free full text".
- Europe PMC search (articles + preprints) with JATS (/fullTextXML) extraction.
- Unpaywall fallback for any DOI → best OA PDF/HTML.
- arXiv, medRxiv, ChemRxiv (via Figshare) kept.
- Saves only items with has_fulltext=True (JATS or parsed text).

Speed-ups in this version:
- Parallel source searches across queries & sources (ThreadPoolExecutor).
- Parallel Phase-1 enrich (JATS / Unpaywall lookups) with backoff.
- Docling-from-URL for PDFs (no pre-download), with graceful fallback to pdfminer.

Knobs:
- max_search_workers: parallelism for search fan-out.
- max_phase1_workers: parallelism for JATS/Unpaywall enrichment.
- max_parallel_docling: parallel Docling conversions (PDF URLs).

Notes:
- If Docling is unavailable, the code silently falls back to pdfminer.
- If Docling import works, we try directly from the PDF URL first.
"""

from __future__ import annotations

import os, re, csv, json, time, string, logging, pathlib, hashlib, io, gc, random, sys, zlib
import subprocess, locale, signal
import importlib.resources as resources
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Type, Any
from contextvars import ContextVar, copy_context
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import pypdf  # Added for PDF chunking
import lancedb # Added for offline DB check
import threading
import time
from functools import lru_cache
try:
    import sqlite3 as _sqlite_mod
    SQLITE_BACKEND = "sqlite3"
except Exception:
    _sqlite_mod = None
    SQLITE_BACKEND = ""
if _sqlite_mod is None:
    import apsw as _sqlite_mod  # type: ignore
    SQLITE_BACKEND = "apsw"

# Serialize execute/fetch on shared SQLite connections used by query workers.
_OFFLINE_SQLITE_QUERY_LOCK = threading.RLock()

# Global lock and timestamp for NCBI rate limiting
_ENTREZ_LOCK = threading.Lock()
_LAST_ENTREZ_CALL = 0.0
ENTREZ_RATE_LIMIT = 0.11  # ~9 requests per second (safe with API key)

# --- START CHANGE ---
try:
    from sentence_transformers import CrossEncoder
    import torch
except ImportError:
    CrossEncoder = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
# --- END CHANGE ---

import requests
import xml.etree.ElementTree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
import fcntl

from Bio import Entrez
from pdfminer.high_level import extract_text as pdf_extract_text
from langchain.tools import BaseTool

# -------------------- Optional Docling --------------------
try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, ThreadedPdfPipelineOptions
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.settings import settings
    _DOCLING_AVAILABLE = True
except Exception:
    DocumentConverter = None  # type: ignore
    PdfFormatOption = None # type: ignore
    InputFormat = None  # type: ignore
    PdfPipelineOptions = None  # type: ignore
    ThreadedPdfPipelineOptions = None # type: ignore
    AcceleratorDevice = None # type: ignore
    AcceleratorOptions = None # type: ignore
    settings = None # type: ignore
    _DOCLING_AVAILABLE = False

# Global lock to prevent parallel Docling/PyTorch execution across multiple tool instances
# _DOCLING_LOCK = Lock() # Removed to allow parallel conversion


log = logging.getLogger("fulltext_journal_search")
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

FULLTEXT_SEARCH_DEFAULT_MAX_RESULTS = int(os.environ.get("FULLTEXT_SEARCH_DEFAULT_MAX_RESULTS", "50"))
FULLTEXT_SEARCH_ADAPTIVE_SCORE_THRESHOLD = float(os.environ.get("FULLTEXT_SEARCH_ADAPTIVE_SCORE_THRESHOLD", "0.20"))
FULLTEXT_SEARCH_MIN_SAFE_KEEP = int(os.environ.get("FULLTEXT_SEARCH_MIN_SAFE_KEEP", "5"))
FULLTEXT_SEARCH_RRF_K = int(os.environ.get("FULLTEXT_SEARCH_RRF_K", "60"))
FULLTEXT_SEARCH_MAX_QUERIES = int(os.environ.get("FULLTEXT_SEARCH_MAX_QUERIES", "12"))
FULLTEXT_SEARCH_RRF_FILTER_ENABLE = os.environ.get("FULLTEXT_SEARCH_RRF_FILTER_ENABLE", "1").strip().lower() not in {"0", "false", "no"}
FULLTEXT_SEARCH_RRF_RELATIVE_THRESHOLD = float(os.environ.get("FULLTEXT_SEARCH_RRF_RELATIVE_THRESHOLD", "0.15"))
FULLTEXT_SEARCH_RRF_MIN_HITS = int(os.environ.get("FULLTEXT_SEARCH_RRF_MIN_HITS", "1"))
FULLTEXT_SEARCH_RRF_MIN_KEEP = int(os.environ.get("FULLTEXT_SEARCH_RRF_MIN_KEEP", "200"))
FULLTEXT_SEARCH_RRF_MAX_KEEP = int(os.environ.get("FULLTEXT_SEARCH_RRF_MAX_KEEP", "0"))
FULLTEXT_PDF_FAIL_CIRCUIT_THRESHOLD = int(os.environ.get("FULLTEXT_PDF_FAIL_CIRCUIT_THRESHOLD", "2"))
FULLTEXT_PDF_FAIL_CIRCUIT_SECONDS = int(os.environ.get("FULLTEXT_PDF_FAIL_CIRCUIT_SECONDS", "600"))
FULLTEXT_PDF_DOWNLOAD_CONNECT_TIMEOUT = float(os.environ.get("FULLTEXT_PDF_DOWNLOAD_CONNECT_TIMEOUT", "4"))
FULLTEXT_PDF_DOWNLOAD_READ_TIMEOUT = float(os.environ.get("FULLTEXT_PDF_DOWNLOAD_READ_TIMEOUT", "12"))
FULLTEXT_PDF_RESOLVE_CONNECT_TIMEOUT = float(os.environ.get("FULLTEXT_PDF_RESOLVE_CONNECT_TIMEOUT", "3"))
FULLTEXT_PDF_RESOLVE_READ_TIMEOUT = float(os.environ.get("FULLTEXT_PDF_RESOLVE_READ_TIMEOUT", "6"))
FULLTEXT_PDF_DOWNLOAD_USE_RETRY_SESSION = os.environ.get("FULLTEXT_PDF_DOWNLOAD_USE_RETRY_SESSION", "0").strip().lower() in {"1", "true", "yes", "on"}
FULLTEXT_PDF_TEXT_EXTRACTOR = os.environ.get("FULLTEXT_PDF_TEXT_EXTRACTOR", "opendataloader").strip().lower()
FULLTEXT_ODL_USE_HYBRID = os.environ.get("FULLTEXT_ODL_USE_HYBRID", "1").strip().lower() not in {"0", "false", "no"}
FULLTEXT_ODL_HYBRID_MODEL = os.environ.get("FULLTEXT_ODL_HYBRID_MODEL", "docling-fast").strip()
FULLTEXT_ODL_HYBRID_MODE = os.environ.get("FULLTEXT_ODL_HYBRID_MODE", "").strip()
FULLTEXT_ODL_HYBRID_URL = os.environ.get("FULLTEXT_ODL_HYBRID_URL", "").strip()
FULLTEXT_ODL_HYBRID_TIMEOUT = os.environ.get("FULLTEXT_ODL_HYBRID_TIMEOUT", "").strip()
FULLTEXT_ODL_HYBRID_FALLBACK = os.environ.get("FULLTEXT_ODL_HYBRID_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}
FULLTEXT_ODL_CONVERT_TIMEOUT_SECONDS = int(os.environ.get("FULLTEXT_ODL_CONVERT_TIMEOUT_SECONDS", "180"))
FULLTEXT_CACHE_DIR = os.environ.get("FULLTEXT_CACHE_DIR", "/data/chen/e2e_searching_results/cache").strip()
FULLTEXT_OFFLINE_SQLITE_PATH = os.environ.get("OFFLINE_SQLITE_PATH", "").strip()
FULLTEXT_OFFLINE_VECTOR_MODEL = os.environ.get("OFFLINE_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip() or "BAAI/bge-small-en-v1.5"
FULLTEXT_ENABLE_OFFLINE_VECTOR_SEARCH = os.environ.get("ENABLE_OFFLINE_VECTOR_SEARCH", "0").strip().lower() in {"1", "true", "yes", "on"}
FULLTEXT_RERANK_MODEL = os.environ.get("FULLTEXT_RERANK_MODEL", "BAAI/bge-reranker-v2-m3").strip() or "BAAI/bge-reranker-v2-m3"
FULLTEXT_RERANK_FALLBACK_MODEL = os.environ.get("FULLTEXT_RERANK_FALLBACK_MODEL", "").strip()
FULLTEXT_RERANK_DEVICE = os.environ.get("FULLTEXT_RERANK_DEVICE", "").strip().lower()
FULLTEXT_S2_MIN_INTERVAL_WITH_KEY = float(os.environ.get("FULLTEXT_S2_MIN_INTERVAL_WITH_KEY", "1.2"))
FULLTEXT_S2_MIN_INTERVAL_NO_KEY = float(os.environ.get("FULLTEXT_S2_MIN_INTERVAL_NO_KEY", "3.5"))
FULLTEXT_S2_MAX_RETRIES = int(os.environ.get("FULLTEXT_S2_MAX_RETRIES", "4"))


def _normalize_query_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _extract_quoted_phrases(query: str) -> List[str]:
    if not query:
        return []
    return [m.strip() for m in re.findall(r'"([^"]+)"', query) if m and m.strip()]


def _paper_identity_key(item: Dict) -> str:
    ids = item.get("ids", {}) or {}
    doi = (ids.get("doi") or item.get("doi") or "").lower().strip()
    if doi:
        return f"doi:{doi}"
    pmid = (ids.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    pmcid = (ids.get("pmcid") or "").strip()
    if pmcid:
        return f"pmcid:{pmcid}"
    s2id = (ids.get("s2id") or "").strip()
    if s2id:
        return f"s2:{s2id}"
    arxiv_id = (ids.get("arxiv") or "").strip()
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    title = (item.get("title") or "").strip().lower()
    if title:
        return f"title:{title}"
    return f"fallback:{hash(json.dumps(item, sort_keys=True, ensure_ascii=True))}"


def _normalize_string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    deduped: List[str] = []
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


def _dedupe_strings(values: List[str]) -> List[str]:
    deduped: List[str] = []
    seen: set[str] = set()
    for value in values:
        item = (value or "").strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _quote_if_needed(text: str) -> str:
    item = (text or "").strip()
    if not item:
        return ""
    if item.startswith('"') and item.endswith('"'):
        return item
    if " " in item:
        return f'"{item}"'
    return item


def _is_identifier_like_alias(text: str) -> bool:
    item = (text or "").strip()
    if not item:
        return False
    upper = item.upper()
    patterns = [
        r"^\d{2,7}-\d{2}-\d$",
        r"^PUBCHEM CID \d+$",
        r"^CID \d+$",
        r"^UNII[-:\s]?[A-Z0-9]+$",
        r"^CHEBI[:\-]?\d+$",
        r"^CHEMBL\d+$",
        r"^DTXSID[A-Z0-9]+$",
        r"^DTXCID[A-Z0-9]+$",
        r"^HSDB\s*\d+$",
        r"^NSC[-\s]?\d+$",
        r"^CCRIS\s*\d+$",
        r"^EINECS\s*[\d\-]+$",
        r"^EC\s*[\d\-]+$",
        r"^CAS[-:\s]?\d{2,7}-\d{2}-\d$",
    ]
    return any(re.fullmatch(pattern, upper) for pattern in patterns)


def _rank_identity_terms(values: List[str]) -> List[str]:
    ranked: List[tuple[int, int, str]] = []
    for idx, value in enumerate(values):
        item = (value or "").strip()
        if not item:
            continue
        penalty = 1 if _is_identifier_like_alias(item) else 0
        ranked.append((penalty, idx, item))
    ranked.sort(key=lambda x: (x[0], x[1]))
    return [item for _, _, item in ranked]


def _generate_mechanical_query_batch(
    *,
    query: Any = None,
    identity_terms: Any = None,
    context_terms: Any = None,
    max_queries: int = FULLTEXT_SEARCH_MAX_QUERIES,
) -> List[str]:
    def _parse_query_field(q_field: Any) -> List[str]:
        if isinstance(q_field, list):
            return [str(x).strip() for x in q_field if str(x).strip()]
        q_s = str(q_field or "").strip()
        if not q_s:
            return []
        if q_s.startswith("[") and q_s.endswith("]"):
            try:
                parsed = json.loads(q_s)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        if "||" in q_s:
            return [x.strip() for x in q_s.split("||") if x.strip()]
        return [q_s]

    queries = _parse_query_field(query)
    identities = _rank_identity_terms(_normalize_string_list(identity_terms))
    contexts = _normalize_string_list(context_terms)

    generated: List[str] = list(queries)

    if identities:
        primary_identities = identities[:2]
        held_back_identities = identities[2:]

        # Always include the base form for primary identities before consuming budget with context expansions.
        for identity in primary_identities:
            generated.append(_quote_if_needed(identity))

        # Interleave context expansions across primary identities so one identity cannot starve others.
        context_rounds: List[str] = []
        for context in contexts:
            for identity in primary_identities:
                if _is_identifier_like_alias(identity):
                    continue
                context_rounds.append(f"{_quote_if_needed(identity)} {context}".strip())
        generated.extend(context_rounds)

        # Keep additional aliases discoverable, but do not explode them across every context.
        for identity in held_back_identities:
            generated.append(_quote_if_needed(identity))
    elif contexts:
        generated.extend(contexts)

    deduped = _dedupe_strings(generated)
    if max_queries and max_queries > 0:
        return deduped[:max_queries]
    return deduped


def _merge_paper_records(base: Dict, incoming: Dict) -> Dict:
    merged = dict(base)
    for key in ("title", "authors", "journal", "pubdate", "doi", "url", "abstract", "full_text", "pdf_url", "pdf_path", "html_path"):
        if not merged.get(key) and incoming.get(key):
            merged[key] = incoming.get(key)
    if not merged.get("has_fulltext") and incoming.get("has_fulltext"):
        merged["has_fulltext"] = incoming.get("has_fulltext")
    if not merged.get("sections") and incoming.get("sections"):
        merged["sections"] = incoming.get("sections")
    merged_ids = dict(merged.get("ids", {}) or {})
    incoming_ids = dict(incoming.get("ids", {}) or {})
    for key, value in incoming_ids.items():
        if value and not merged_ids.get(key):
            merged_ids[key] = value
    merged["ids"] = merged_ids
    return merged


def _apply_rrf_fusion(items: List[Dict], k: int = FULLTEXT_SEARCH_RRF_K) -> List[Dict]:
    if not items:
        return []

    grouped_runs: Dict[tuple[str, str], List[Dict]] = {}
    for item in items:
        src = str(item.get("_retrieval_source") or item.get("source") or "")
        query = str(item.get("_retrieval_query") or "")
        grouped_runs.setdefault((src, query), []).append(item)

    fused: Dict[str, Dict] = {}
    title_keys: List[tuple[str, str]] = []

    def _locate_existing(key: str, title: str) -> str | None:
        if key in fused:
            return key
        if key.startswith("title:"):
            for existing_key, existing_title in title_keys:
                if title_close(title, existing_title):
                    return existing_key
        return None

    for (_, _), ranked_items in grouped_runs.items():
        for rank, item in enumerate(ranked_items, start=1):
            key = _paper_identity_key(item)
            title = str(item.get("title") or "")
            existing_key = _locate_existing(key, title)
            if existing_key is None:
                entry = dict(item)
                entry["_rrf_score"] = 0.0
                entry["_rrf_hits"] = 0
                entry["_rrf_sources"] = []
                entry["_rrf_queries"] = []
                fused[key] = entry
                existing_key = key
                if key.startswith("title:"):
                    title_keys.append((existing_key, title))
            fused_item = fused[existing_key]
            fused_item["_rrf_score"] = float(fused_item.get("_rrf_score", 0.0)) + (1.0 / (k + rank))
            fused_item["_rrf_hits"] = int(fused_item.get("_rrf_hits", 0)) + 1
            src = str(item.get("_retrieval_source") or item.get("source") or "")
            query = str(item.get("_retrieval_query") or "")
            if src and src not in fused_item["_rrf_sources"]:
                fused_item["_rrf_sources"].append(src)
            if query and query not in fused_item["_rrf_queries"]:
                fused_item["_rrf_queries"].append(query)
            fused[existing_key] = _merge_paper_records(fused_item, item)

    fused_items = list(fused.values())
    fused_items.sort(
        key=lambda x: (
            float(x.get("_rrf_score", 0.0)),
            int(x.get("_rrf_hits", 0)),
            bool(x.get("has_fulltext")),
        ),
        reverse=True,
    )
    return fused_items

# -------------------------------------------------------------------
# ContextVar to carry the per-run session directory (env-free, safe)
# -------------------------------------------------------------------
_SESSION_DIR_CVAR: ContextVar[Optional[str]] = ContextVar("SEARCH_SESSION_DIR", default=None)

# ----------------------------- Models & Utilities -----------------------------
class FullTextJournalSearchInput(BaseModel):
    query: Optional[str | List[str]] = Field(None, description="Legacy: Primary search terms. If offline/online queries are set, this is used as fallback.")
    identity_terms: Optional[List[str]] = Field(None, description="Optional entity names or synonyms to combine mechanically into search queries.")
    context_terms: Optional[List[str]] = Field(None, description="Optional task/context terms to combine mechanically with identity_terms.")
    
    max_results: int = Field(FULLTEXT_SEARCH_DEFAULT_MAX_RESULTS, description="Maximum number of results to return (per source, global default)")
    
    # --- START CHANGE ---
    # Per-source 'k' values. If not set, the global 'max_results' is used.
    max_results_pubmed: Optional[int] = Field(None, description="Max results for PubMed (overrides global max_results)")
    max_results_eupmc: Optional[int] = Field(None, description="Max results for Europe PMC (overrides global max_results)")
    max_results_s2: Optional[int] = Field(None, description="Max results for Semantic Scholar (overrides global max_results)")
    max_results_arxiv: Optional[int] = Field(None, description="Max results for arXiv (overrides global max_results)")
    max_results_medrxiv: Optional[int] = Field(None, description="Max results for medRxiv (overrides global max_results)")
    max_results_chemrxiv: Optional[int] = Field(None, description="Max results for ChemRxiv (overrides global max_results)")
    # --- END CHANGE ---

    # Date range filters
    min_date: Optional[str] = Field(None, description="Minimum publication date (YYYY, YYYY/MM, or YYYY/MM/DD format)")
    max_date: Optional[str] = Field(None, description="Maximum publication date (YYYY, YYYY/MM, or YYYY/MM/DD format)")

    include_preprints: bool = Field(True, description="Include preprints")
    include_pubmed: bool = Field(True, description="Include PubMed/PMC")
    include_s2: bool = Field(True, description="Include Semantic Scholar Graph search")
    include_arxiv: bool = Field(False, description="Include arXiv (off by default)")
    include_medrxiv: bool = Field(True, description="Include medRxiv")
    include_chemrxiv: bool = Field(True, description="Include ChemRxiv (via Figshare)")
    include_eupmc: bool = Field(True, description="Include Europe PMC search (JATS fullTextXML when available)")
    use_pubmed_free_fulltext_bias: bool = Field(False, description="Deprecated compatibility flag; PubMed free full text bias is disabled.")

    # Set more reasonable, conservative defaults to avoid rate-limiting
    max_parallel_downloads: int = Field(4, description="(Legacy) kept for backward compat; not used if Docling is on")
    max_search_workers: int = Field(8, description="Max concurrent search tasks across sources & queries")
    max_phase1_workers: int = Field(12, description="Max concurrent JATS/Unpaywall enrich tasks")
    max_parallel_docling: int = Field(4, description="Max concurrent Docling URL conversions (default 4 for parallel downloads)")
    processing_chunk_size: int = Field(20, description="Number of papers to process in a single in-memory chunk")
    
    # --- START CHANGE ---
    offline_index_path: Optional[str] = Field(None, description="Path to LanceDB offline vector shards used by the fused offline retriever.")
    offline_sqlite_path: Optional[str] = Field(None, description="Path to SQLite doc-level offline metadata DB.")
    offline_doc_dir: Optional[str] = Field("/data/chen/pubmed_corpus/pmc_extracted_text", description="Path to offline text files")
    enable_offline_vector_search: bool = Field(FULLTEXT_ENABLE_OFFLINE_VECTOR_SEARCH, description="Enable optional vector expansion from LanceDB offline vector shards.")
    offline_vector_model: Optional[str] = Field(None, description="Embedding model name used for offline LanceDB vector shards.")
    # --- END CHANGE ---


def make_requests_session(total_retries: int = 5, backoff: float = 0.5,status_forcelist=(429, 500, 502, 503, 504)) -> requests.Session:
    retry = Retry(
        total=total_retries, read=total_retries, connect=total_retries,
        backoff_factor=backoff, status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "POST"]), raise_on_status=False,
        )
    adapter = HTTPAdapter(max_retries=retry)
    # --- START CHANGE ---
    # Increase pool size to handle high concurrency
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=50,  # Default is 10
        pool_maxsize=50       # Default is 10
    )
    # --- END CHANGE ---
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Enhanced-Journal-Search/2.0 (mailto: laozc@student.ubc.ca)"})
    sess.mount("http://", adapter); sess.mount("https://", adapter)
    return sess


def sanitize_filename(name: str, max_len: int = 120) -> str:
    original = name
    name = re.sub(r"\s+", " ", name or "").strip()
    allowed = f"-_.() {string.ascii_letters}{string.digits}"
    cleaned = "".join(c for c in name if c in allowed)
    if cleaned:
        return cleaned[:max_len]
    # fall back to deterministic hash on original (may contain disallowed chars)
    return hashlib.sha1((original or "").encode()).hexdigest()[:16]


def best_identifier_url(ids: Dict[str, Any]) -> str:
    doi = str((ids or {}).get("doi") or "").strip()
    pmid = str((ids or {}).get("pmid") or "").strip()
    pmcid = str((ids or {}).get("pmcid") or "").strip()
    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if pmcid:
        if not pmcid.startswith("PMC"):
            pmcid = f"PMC{pmcid}"
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    return ""


def build_sqlite_fts_query(query: str) -> str:
    raw = (query or "").strip()
    if not raw:
        return ""

    phrases = [m.strip() for m in re.findall(r'"([^"]+)"', raw) if m and m.strip()]
    base = re.sub(r'"[^"]+"', " ", raw)
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-\._/]*", base)

    parts: List[str] = []
    for phrase in phrases[:4]:
        parts.append(f'"{phrase}"')
    for token in tokens[:20]:
        if len(token) > 1:
            parts.append(token)

    out: List[str] = []
    seen = set()
    for item in parts:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return " OR ".join(out[:12])


def build_sqlite_like_terms(query: str) -> List[str]:
    raw = (query or "").strip()
    if not raw:
        return []
    phrases = [m.strip() for m in re.findall(r'"([^"]+)"', raw) if m and m.strip()]
    base = re.sub(r'"[^"]+"', " ", raw)
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-\._/]*", base)
    terms: List[str] = []
    for phrase in phrases[:4]:
        terms.append(phrase)
    for token in tokens[:20]:
        if len(token) > 2:
            terms.append(token)
    return _dedupe_strings(terms[:12])


@lru_cache(maxsize=200000)
def _normalize_offline_doc_id(raw_doc_id: str) -> str:
    text = str(raw_doc_id or "").strip()
    if not text:
        return ""
    if text.startswith("pmcid:PMC"):
        return text
    pmcid_match = re.search(r"(PMC\d+)", text, flags=re.IGNORECASE)
    if pmcid_match:
        return f"pmcid:{pmcid_match.group(1).upper()}"
    return text


def _pmcid_from_doc_id(raw_doc_id: str) -> str:
    normalized = _normalize_offline_doc_id(raw_doc_id)
    if normalized.startswith("pmcid:PMC"):
        return normalized.split(":", 1)[1]
    return ""


def norm_title(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb: return 0.0
    return len(sa & sb) / len(sa | sb)


def title_close(a: str, b: str) -> bool:
    A, B = norm_title(a), norm_title(b)
    if not A or not B: return False
    return jaccard(A, B) >= 0.72


def first(*vals: Optional[str]) -> str:
    for v in vals:
        if v: return v
    return ""


def _normalize_flat_text(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\ufb01": "fi",
        "\ufb02": "fl",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def _jats_text_without_xrefs(node: ET.Element) -> str:
    parts: List[str] = []

    def walk(elem: ET.Element) -> None:
        if elem.text:
            parts.append(elem.text)
        for child in list(elem):
            # Skip inline reference/footnote text that commonly gets glued onto names,
            # e.g. "Dichloracetamideb" where "b" is a table footnote/xref marker.
            if child.tag in {"xref", "label"}:
                if child.tail:
                    parts.append(child.tail)
                continue
            walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(node)
    return _normalize_flat_text("".join(parts))


def _clean_html_text(node) -> str:
    if node is None:
        return ""
    node = node.__copy__() if hasattr(node, "__copy__") else BeautifulSoup(str(node), "html.parser")
    for tag in node.find_all("sup"):
        txt = tag.get_text(" ", strip=True)
        if txt and len(txt) <= 3 and re.fullmatch(r"[A-Za-z0-9]+", txt):
            tag.decompose()
    return _normalize_flat_text(node.get_text(" ", strip=True))


def jats_nodes_to_sections(root: ET.Element) -> List[Dict[str, str]]:
    sections: List[Dict[str, str]] = []
    body = root.find(".//body")
    targets = [body] if body is not None else root.findall(".//sec")

    def clean_text(element_text):
        if not element_text:
            return ""
        return _normalize_flat_text(element_text)

    def parse_table(table_node):
        rows = []
        # thead
        thead = table_node.find("thead")
        if thead is not None:
            for tr in thead.findall("tr"):
                cells = [_jats_text_without_xrefs(th) for th in tr.findall("th")]
                if not cells:
                    cells = [_jats_text_without_xrefs(td) for td in tr.findall("td")]
                rows.append("| " + " | ".join(cells) + " |")
                rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
        # tbody
        tbody = table_node.find("tbody")
        if tbody is not None:
            for tr in tbody.findall("tr"):
                cells = [_jats_text_without_xrefs(td) for td in tr.findall("td")]
                rows.append("| " + " | ".join(cells) + " |")
        return "\n".join(rows)

    for target_node in targets:
        for sec in target_node.findall("./sec"):
            title = clean_text(sec.findtext("title"))
            text_parts = [_jats_text_without_xrefs(p) for p in sec.findall(".//p")]
            
            # Extract tables
            tables = []
            for tw in sec.findall(".//table-wrap"):
                label = clean_text(tw.findtext("label"))
                caption = _jats_text_without_xrefs(tw.find("caption")) if tw.find("caption") is not None else ""
                t_content = ""
                table_node = tw.find("table")
                if table_node is not None:
                    t_content = parse_table(table_node)
                table_str = f"\n\n**Table: {label}**\n*{caption}*\n{t_content}\n"
                tables.append(table_str)

            text = "\n".join(part for part in text_parts if part)
            if tables:
                text += "\n" + "\n".join(tables)

            if title or text:
                sections.append({"title": title, "text": text})

    if not sections and body is not None:
        text_parts = [_jats_text_without_xrefs(p) for p in body.findall(".//p")]
        
        # Extract tables (fallback)
        tables = []
        for tw in body.findall(".//table-wrap"):
            label = clean_text(tw.findtext("label"))
            caption = _jats_text_without_xrefs(tw.find("caption")) if tw.find("caption") is not None else ""
            t_content = ""
            table_node = tw.find("table")
            if table_node is not None:
                t_content = parse_table(table_node)
            table_str = f"\n\n**Table: {label}**\n*{caption}*\n{t_content}\n"
            tables.append(table_str)

        txt = "\n".join(part for part in text_parts if part)
        if tables:
            txt += "\n" + "\n".join(tables)

        if txt:
            sections.append({"title": "", "text": txt})
    return sections


def sections_to_markdown(sections: List[Dict[str, str]]) -> str:
    return "\n\n".join(
        [f"## {s['title']}\n{s['text']}" if s.get("title") else s.get("text","") for s in sections]
    ).strip()


def pmc_html_to_sections(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    article = soup.select_one("main article") or soup.select_one("article")
    if article is None:
        return []

    sections: List[Dict[str, str]] = []

    def _clean_text(text: str) -> str:
        return _normalize_flat_text(text or "")

    def _section_title(node) -> str:
        heading = None
        for selector in ("h2.pmc_sec_title", "h3.pmc_sec_title", "h2", "h3"):
            heading = node.select_one(selector)
            if heading is not None:
                break
        return _clean_html_text(heading) if heading is not None else ""

    def _section_text(node) -> str:
        paragraphs: List[str] = []
        for p in node.find_all("p"):
            text = _clean_html_text(p)
            if text:
                paragraphs.append(text)
        return "\n\n".join(paragraphs)

    abstract_section = article.select_one("section.abstract")
    if abstract_section is not None:
        abstract_text = _section_text(abstract_section)
        if abstract_text:
            sections.append({"title": "Abstract", "text": abstract_text})

    body_section = article.select_one("section.body.main-article-body") or article.select_one("section.body")
    if body_section is not None:
        for child in body_section.find_all("section", recursive=False):
            title = _section_title(child)
            text = _section_text(child)
            if title or text:
                sections.append({"title": title, "text": text})

    if sections:
        return sections

    fallback_text = _clean_html_text(article)
    if fallback_text:
        return [{"title": "", "text": fallback_text}]
    return []


# ----------------------------- Main Tool -----------------------------
class FullTextJournalSearchTool(BaseTool):
    name: str = "fulltext_journal_search"
    description: str = "Fetch articles from PubMed/PMC, Europe PMC, and preprint servers; save full text when available."
    args_schema: Type[FullTextJournalSearchInput] = FullTextJournalSearchInput

    _entrez_email: str = "laozc@student.ubc.ca"
    _max_retries: int = 5
    _backoff_base: float = 2.0
    _http: requests.Session

    include_online_search: bool = True # Added for global toggle
    include_pubmed: bool = True
    include_preprints: bool = True
    include_s2: bool = True
    include_arxiv: bool = True
    include_medrxiv: bool = True
    include_chemrxiv: bool = True
    include_eupmc: bool = True
    use_pubmed_free_fulltext_bias: bool = False

    # parallel knobs (default overridden by input if provided)
    # parallel knobs (default overridden by input if provided)
    max_parallel_downloads: int = 2  # legacy
    max_search_workers: int = 2
    max_phase1_workers: int = 4
    max_parallel_docling: int = 2

    results_base_dir: Optional[pathlib.Path] = None
    
    # Date range filters
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    
    # Offline DB
    include_offline_search: bool = True
    offline_index_path: Optional[str] = None
    offline_sqlite_path: Optional[str] = None
    offline_doc_dir: Optional[str] = None
    enable_offline_vector_search: bool = FULLTEXT_ENABLE_OFFLINE_VECTOR_SEARCH
    offline_vector_model: str = FULLTEXT_OFFLINE_VECTOR_MODEL
    pdf_text_extractor: str = FULLTEXT_PDF_TEXT_EXTRACTOR
    odl_use_hybrid: bool = FULLTEXT_ODL_USE_HYBRID
    odl_hybrid_model: str = FULLTEXT_ODL_HYBRID_MODEL
    odl_hybrid_mode: str = FULLTEXT_ODL_HYBRID_MODE
    odl_hybrid_url: str = FULLTEXT_ODL_HYBRID_URL
    odl_hybrid_timeout: str = FULLTEXT_ODL_HYBRID_TIMEOUT
    odl_hybrid_fallback: bool = FULLTEXT_ODL_HYBRID_FALLBACK
    cache_dir: str = FULLTEXT_CACHE_DIR

    def __init__(self, **data):
        super().__init__(**data)
        self._http = make_requests_session()
        self._current_run_assets_dir: Optional[pathlib.Path] = data.get("results_base_dir", None)
        # Ensure it's a Path object if provided
        if self._current_run_assets_dir and isinstance(self._current_run_assets_dir, str):
            self._current_run_assets_dir = pathlib.Path(self._current_run_assets_dir)

        # flags (allow override via constructor)
        self.include_online_search = data.get("include_online_search", True) # Added
        self.include_pubmed = data.get("include_pubmed", True)
        self.include_preprints = data.get("include_preprints", True)
        self.include_s2 = data.get("include_s2", True)
        self.include_arxiv = data.get("include_arxiv", False)
        self.include_medrxiv = data.get("include_medrxiv", True)
        self.include_chemrxiv = data.get("include_chemrxiv", True)
        self.include_eupmc = data.get("include_eupmc", True)
        self.include_offline_search = data.get("include_offline_search", True) # Added
        self.offline_index_path = str(data.get("offline_index_path", "") or "").strip() or None
        self.offline_sqlite_path = str(data.get("offline_sqlite_path", FULLTEXT_OFFLINE_SQLITE_PATH) or FULLTEXT_OFFLINE_SQLITE_PATH).strip() or None
        self.enable_offline_vector_search = bool(data.get("enable_offline_vector_search", FULLTEXT_ENABLE_OFFLINE_VECTOR_SEARCH))
        self.offline_vector_model = str(data.get("offline_vector_model", FULLTEXT_OFFLINE_VECTOR_MODEL) or FULLTEXT_OFFLINE_VECTOR_MODEL).strip() or FULLTEXT_OFFLINE_VECTOR_MODEL
        self.use_pubmed_free_fulltext_bias = data.get("use_pubmed_free_fulltext_bias", False)
        self.max_parallel_downloads = int(data.get("max_parallel_downloads", 4))
        self.max_search_workers = int(data.get("max_search_workers", 4))
        self.max_phase1_workers = int(data.get("max_phase1_workers", 4))
        self.max_parallel_docling = int(data.get("max_parallel_docling", 1))
        extractor = str(data.get("pdf_text_extractor", FULLTEXT_PDF_TEXT_EXTRACTOR) or "docling").strip().lower()
        self.pdf_text_extractor = extractor if extractor in {"docling", "opendataloader"} else "docling"
        self.odl_use_hybrid = bool(data.get("odl_use_hybrid", FULLTEXT_ODL_USE_HYBRID))
        self.odl_hybrid_model = str(data.get("odl_hybrid_model", FULLTEXT_ODL_HYBRID_MODEL) or "").strip()
        self.odl_hybrid_mode = str(data.get("odl_hybrid_mode", FULLTEXT_ODL_HYBRID_MODE) or "").strip()
        self.odl_hybrid_url = str(data.get("odl_hybrid_url", FULLTEXT_ODL_HYBRID_URL) or "").strip()
        self.odl_hybrid_timeout = str(data.get("odl_hybrid_timeout", FULLTEXT_ODL_HYBRID_TIMEOUT) or "").strip()
        self.odl_hybrid_fallback = bool(data.get("odl_hybrid_fallback", FULLTEXT_ODL_HYBRID_FALLBACK))
        self.cache_dir = str(data.get("cache_dir", FULLTEXT_CACHE_DIR) or FULLTEXT_CACHE_DIR).strip()
        self._cache_root = pathlib.Path(self.cache_dir)
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._resolution_cache_dir = self._cache_root / "resolution"
        self._fulltext_cache_dir = self._cache_root / "fulltext"
        self._pmcid_cache_dir = self._cache_root / "pmcid"
        for _dir in (self._resolution_cache_dir, self._fulltext_cache_dir, self._pmcid_cache_dir):
            _dir.mkdir(parents=True, exist_ok=True)

        # Note: min_date and max_date are now Pydantic fields, so they're set automatically
        
        # Docling converter (optional)
        if _DOCLING_AVAILABLE:
            # Configure accelerator options for GPU
            accelerator_options = AcceleratorOptions(
                num_threads=self.max_parallel_docling, 
                device=AcceleratorDevice.CUDA
            )

            # Use ThreadedPdfPipelineOptions for better batch control on GPU
            pipeline_options = ThreadedPdfPipelineOptions(
                do_ocr=False,
                do_table_structure=True,
                ocr_batch_size=16,    # Optimized for GPU
                layout_batch_size=16, # Optimized for GPU
                table_batch_size=16,  # Optimized for GPU
                accelerator_options=accelerator_options
            )
            
            # Set global page batch size for GPU inference
            settings.perf.page_batch_size = 16

            self._docling = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )
        else:
            self._docling = None
            
        # Initialize runtime attributes
        self._offline_sqlite_conn = None
        self._offline_sqlite_conns: List[Tuple[str, Any]] = []
        self._offline_vector_db = None
        self._offline_vector_tables: List[Tuple[str, Any]] = []
        self._offline_vector_embedder = None
        self._offline_doc_lookup_cache: Dict[str, Dict[str, Any]] = {}
        self._cross_encoder = None
        self._download_fail_counts: Dict[str, int] = {}
        self._download_circuit_until: Dict[str, float] = {}

        if self.offline_sqlite_path:
            try:
                self._offline_sqlite_conn = self._init_offline_doc_db(self.offline_sqlite_path)
            except Exception as e:
                log.warning(f"Failed to initialize offline SQLite DB {self.offline_sqlite_path}: {e}")

    def _get_effective_assets_dir(self) -> Optional[pathlib.Path]:
        """Resolve the directory to save assets (PDFs, XMLs), preferring the context var."""
        session_dir = _SESSION_DIR_CVAR.get()
        if session_dir:
            # Create an 'assets' subdirectory for the actual files
            p = pathlib.Path(session_dir) / "assets"
            p.mkdir(parents=True, exist_ok=True)
            return p
        if self._current_run_assets_dir:
            return self._current_run_assets_dir if isinstance(self._current_run_assets_dir, pathlib.Path) else pathlib.Path(self._current_run_assets_dir)
        return None

    def _cache_path(self, cache_dir: pathlib.Path, key: str) -> pathlib.Path:
        safe_key = hashlib.sha1((key or "").encode("utf-8")).hexdigest()
        return cache_dir / f"{safe_key}.json"

    def _read_json_cache(self, cache_dir: pathlib.Path, key: str) -> Optional[dict]:
        path = self._cache_path(cache_dir, key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_json_cache(self, cache_dir: pathlib.Path, key: str, payload: dict) -> None:
        path = self._cache_path(cache_dir, key)
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(path)
        except Exception as e:
            log.debug(f"Cache write failed for {path}: {e}")
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

    def _init_offline_doc_db(self, db_path: str):
        path = pathlib.Path(db_path)
        db_paths: List[pathlib.Path]
        if path.is_dir():
            db_paths = sorted(path.glob("offline_docs_shard_*.sqlite"))
            if not db_paths:
                raise FileNotFoundError(f"No shard sqlite files found under {db_path}")
        else:
            db_paths = [path]

        conns: List[Tuple[str, Any]] = []
        for candidate in db_paths:
            if SQLITE_BACKEND == "sqlite3":
                conn = _sqlite_mod.connect(str(candidate), check_same_thread=False)
                conn.row_factory = _sqlite_mod.Row
            else:
                conn = _sqlite_mod.Connection(str(candidate))
            conns.append((str(candidate), conn))

        self._offline_sqlite_conns = conns
        self._offline_sqlite_conn = conns[0][1] if conns else None
        return self._offline_sqlite_conn

    def _sqlite_run_fetchall(self, conn: Any, sql: str, params: Tuple[Any, ...]) -> List[Any]:
        with _OFFLINE_SQLITE_QUERY_LOCK:
            if SQLITE_BACKEND == "sqlite3":
                cur = conn.execute(sql, params)
                return cur.fetchall()
            cur = conn.cursor()
            cur.execute(sql, params)
            return list(cur)

    def _sqlite_row_get(self, row: Any, name: str, columns: List[str]) -> Any:
        if SQLITE_BACKEND == "sqlite3":
            return row[name]
        if name in columns:
            idx = columns.index(name)
            if idx < len(row):
                return row[idx]
            return None
        return None

    def _offline_sqlite_shard_index(self, normalized_doc_id: str) -> int:
        shard_count = len(self._offline_sqlite_conns)
        if shard_count <= 1:
            return 0
        return zlib.crc32(normalized_doc_id.encode("utf-8")) % shard_count

    def _lookup_offline_doc_record(self, normalized_doc_id: str) -> Optional[Dict[str, Any]]:
        normalized_doc_id = _normalize_offline_doc_id(normalized_doc_id)
        if not normalized_doc_id:
            return None
        cached = self._offline_doc_lookup_cache.get(normalized_doc_id)
        if cached is not None:
            return dict(cached)

        columns = [
            "doc_id", "title", "abstract", "doi", "pmid", "pmcid", "year",
            "journal", "authors", "source", "url", "local_txt_path", "local_pdf_path",
        ]
        sql = """
        SELECT doc_id, title, abstract, doi, pmid, pmcid, year,
               journal, authors, source, url, local_txt_path, local_pdf_path
        FROM documents
        WHERE doc_id = ?
        LIMIT 1
        """
        sqlite_conns = self._offline_sqlite_conns or ([("single", self._offline_sqlite_conn)] if self._offline_sqlite_conn else [])
        if not sqlite_conns:
            return None

        preferred_idx = self._offline_sqlite_shard_index(normalized_doc_id)
        ordered = sqlite_conns[preferred_idx:preferred_idx + 1] + sqlite_conns[:preferred_idx] + sqlite_conns[preferred_idx + 1:]
        for _, conn in ordered:
            try:
                rows = self._sqlite_run_fetchall(conn, sql, (normalized_doc_id,))
            except Exception:
                continue
            if not rows:
                continue
            row = rows[0]
            record = {col: self._sqlite_row_get(row, col, columns) or "" for col in columns}
            self._offline_doc_lookup_cache[normalized_doc_id] = dict(record)
            return record
        return None

    def _init_offline_vector_search(self) -> bool:
        if self._offline_vector_tables:
            return True
        if not self.offline_index_path or not os.path.exists(self.offline_index_path):
            return False
        try:
            self._offline_vector_db = lancedb.connect(self.offline_index_path)
            table_names = []
            if hasattr(self._offline_vector_db, "table_names"):
                table_names = list(self._offline_vector_db.table_names())
            elif hasattr(self._offline_vector_db, "list_tables"):
                table_names = list(self._offline_vector_db.list_tables())

            preferred = [
                name for name in table_names
                if re.fullmatch(r"papers_index_fullctx_s\d+", str(name))
            ]
            if not preferred and "papers_index_fullctx" in table_names:
                preferred = ["papers_index_fullctx"]
            tables: List[Tuple[str, Any]] = []
            for name in sorted(preferred):
                try:
                    tables.append((str(name), self._offline_vector_db.open_table(str(name))))
                except Exception as e:
                    log.debug(f"Failed to open offline vector table {name}: {e}")
            self._offline_vector_tables = tables
            if not tables:
                return False
        except Exception as e:
            log.warning(f"Failed to initialize offline vector search from {self.offline_index_path}: {e}")
            return False
        return True

    def _get_offline_vector_embedder(self):
        if self._offline_vector_embedder is not None:
            return self._offline_vector_embedder
        from lancedb.embeddings import get_registry
        registry = get_registry()
        try:
            self._offline_vector_embedder = registry.get("huggingface").create(
                name=self.offline_vector_model,
                device="cuda",
            )
        except Exception as e:
            log.warning(f"Could not load offline vector model on CUDA: {e}. Falling back to CPU.")
            self._offline_vector_embedder = registry.get("huggingface").create(name=self.offline_vector_model)
        return self._offline_vector_embedder

    def _search_offline_doc_db_lexical(self, query: str, max_results: int) -> List[Dict]:
        results: List[Dict] = []
        if not self._offline_sqlite_conn and not self._offline_sqlite_conns:
            return results

        fts_query = build_sqlite_fts_query(query)
        columns = [
            "doc_id", "title", "abstract", "doi", "pmid", "pmcid", "year",
            "journal", "authors", "source", "url", "local_txt_path", "local_pdf_path",
        ]
        sqlite_conns = self._offline_sqlite_conns or [("single", self._offline_sqlite_conn)]
        shard_limit = max(int(max_results), 1)
        deduped: Dict[str, Dict[str, Any]] = {}

        for db_label, conn in sqlite_conns:
            rows: List[Any] = []
            try:
                if fts_query:
                    rows = self._sqlite_run_fetchall(
                        conn,
                        """
                        SELECT d.doc_id, d.title, d.abstract, d.doi, d.pmid, d.pmcid, d.year,
                               d.journal, d.authors, d.source, d.url, d.local_txt_path, d.local_pdf_path,
                               bm25(documents_fts, 10.0, 4.0, 2.0) AS lexical_rank
                        FROM documents_fts f
                        JOIN documents d ON d.doc_id = f.doc_id
                        WHERE documents_fts MATCH ?
                        ORDER BY bm25(documents_fts, 10.0, 4.0, 2.0)
                        LIMIT ?
                        """,
                        (fts_query, shard_limit),
                    )
            except Exception as e:
                log.debug(f"Offline SQLite FTS query failed for '{query[:80]}' on {db_label}: {e}")

            if not rows:
                like_terms = build_sqlite_like_terms(query)
                try:
                    if like_terms:
                        where_parts: List[str] = []
                        params: List[Any] = []
                        for term in like_terms:
                            like = f"%{term}%"
                            where_parts.append("(title LIKE ? OR abstract LIKE ? OR doi LIKE ? OR pmid LIKE ? OR pmcid LIKE ?)")
                            params.extend([like, like, like, like, like])
                        sql = f"""
                        SELECT doc_id, title, abstract, doi, pmid, pmcid, year,
                               journal, authors, source, url, local_txt_path, local_pdf_path, NULL AS lexical_rank
                        FROM documents
                        WHERE {' OR '.join(where_parts)}
                        LIMIT ?
                        """
                        params.append(int(shard_limit))
                        rows = self._sqlite_run_fetchall(conn, sql, tuple(params))
                except Exception as e:
                    log.warning(f"Offline SQLite LIKE query failed for '{query[:80]}' on {db_label}: {e}")
                    rows = []

            for row in rows:
                doc_id = _normalize_offline_doc_id(self._sqlite_row_get(row, "doc_id", columns) or "")
                if not doc_id or doc_id in deduped:
                    continue
                ids = {
                    "doi": self._sqlite_row_get(row, "doi", columns) or "",
                    "pmid": self._sqlite_row_get(row, "pmid", columns) or "",
                    "pmcid": self._sqlite_row_get(row, "pmcid", columns) or _pmcid_from_doc_id(doc_id),
                }
                abstract = str(self._sqlite_row_get(row, "abstract", columns) or "")
                title = self._sqlite_row_get(row, "title", columns) or ""
                lexical_rank = self._sqlite_row_get(
                    row,
                    "lexical_rank",
                    columns + ["lexical_rank"],
                )
                if lexical_rank is not None:
                    # SQLite FTS5 bm25() returns lower-is-better scores, often negative.
                    # Flip the sign so larger scores are better downstream.
                    score = float(-lexical_rank)
                else:
                    score = 0.0
                    if query:
                        ql = (query or "").lower()
                        ttl = str(title).lower()
                        abl = abstract.lower()
                        if ql and ql in ttl:
                            score += 3.0
                        if ql and ql in abl:
                            score += 2.0
                        score += sum(1.0 for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-\\._/]*", ql) if len(tok) > 1 and (tok in ttl or tok in abl))
                deduped[doc_id] = {
                    "source": "offline_db",
                    "title": title,
                    "abstract": abstract,
                    "full_text": "",
                    "offline_chunk_text": abstract,
                    "offline_doc_id": doc_id,
                    "has_fulltext": False,
                    "doi": self._sqlite_row_get(row, "doi", columns) or "",
                    "url": (self._sqlite_row_get(row, "url", columns) or best_identifier_url(ids)),
                    "ids": ids,
                    "pubdate": self._sqlite_row_get(row, "year", columns) or "",
                    "journal": self._sqlite_row_get(row, "journal", columns) or "",
                    "authors": self._sqlite_row_get(row, "authors", columns) or "",
                    "local_txt_path": self._sqlite_row_get(row, "local_txt_path", columns) or "",
                    "local_pdf_path": self._sqlite_row_get(row, "local_pdf_path", columns) or "",
                    "score": float(score),
                }

        results = sorted(deduped.values(), key=lambda x: x.get("score", 0.0), reverse=True)[:max_results]
        if results:
            log.info(f"Offline SQLite lexical search for '{query[:80]}' found {len(results)} items.")
        return results

    def _search_offline_vector_db(self, query: str, max_results: int) -> List[Dict]:
        if not self.enable_offline_vector_search:
            return []
        if not self._offline_sqlite_conn and not self._offline_sqlite_conns:
            return []
        if not self._init_offline_vector_search():
            return []

        try:
            embedder = self._get_offline_vector_embedder()
            qvec = embedder.compute_source_embeddings([query])[0]
            qvec = [float(v) for v in qvec]
        except Exception as e:
            log.warning(f"Offline vector embedding failed for '{query[:80]}': {e}")
            return []

        chunk_limit = max(int(max_results), 1)
        doc_hits: Dict[str, Dict[str, Any]] = {}
        for table_name, table in self._offline_vector_tables:
            try:
                df = (
                    table.search(qvec, vector_column_name="vector", query_type="vector")
                    .limit(chunk_limit)
                    .to_pandas()
                )
            except Exception as e:
                log.debug(f"Offline vector query failed on {table_name}: {e}")
                continue

            for _, row in df.iterrows():
                normalized_doc_id = _normalize_offline_doc_id(str(row.get("doc_id", "") or ""))
                if not normalized_doc_id:
                    continue
                distance = float(row.get("_distance", 0.0) or 0.0)
                existing = doc_hits.get(normalized_doc_id)
                if existing is not None and distance >= float(existing.get("_offline_vector_distance", 1e9)):
                    continue

                meta = self._lookup_offline_doc_record(normalized_doc_id) or {}
                pmcid = str(meta.get("pmcid") or _pmcid_from_doc_id(normalized_doc_id) or "")
                ids = {
                    "doi": str(meta.get("doi") or ""),
                    "pmid": str(meta.get("pmid") or ""),
                    "pmcid": pmcid,
                }
                title = str(meta.get("title") or row.get("title") or "")
                abstract = str(meta.get("abstract") or "")
                vector_text = str(row.get("text") or "")
                doc_hits[normalized_doc_id] = {
                    "source": "offline_db",
                    "title": title,
                    "abstract": abstract,
                    "full_text": "",
                    "offline_chunk_text": vector_text,
                    "offline_doc_id": normalized_doc_id,
                    "has_fulltext": False,
                    "doi": ids["doi"],
                    "url": str(meta.get("url") or best_identifier_url(ids)),
                    "ids": ids,
                    "pubdate": str(meta.get("year") or row.get("year") or ""),
                    "journal": str(meta.get("journal") or ""),
                    "authors": str(meta.get("authors") or ""),
                    "local_txt_path": str(meta.get("local_txt_path") or ""),
                    "local_pdf_path": str(meta.get("local_pdf_path") or ""),
                    "score": float(-distance),
                    "_offline_vector_distance": distance,
                }

        results = sorted(
            doc_hits.values(),
            key=lambda x: float(x.get("_offline_vector_distance", 1e9)),
        )[:max_results]
        if results:
            log.info(f"Offline vector search for '{query[:80]}' found {len(results)} items.")
        return results

    def _search_offline_doc_db(self, query: str, max_results: int) -> List[Dict]:
        lexical_hits = self._search_offline_doc_db_lexical(query, max_results)
        vector_hits = self._search_offline_vector_db(query, max_results)

        if lexical_hits and not vector_hits:
            if not self.enable_offline_vector_search:
                log.info("Offline retrieval using SQLite lexical only for '%s'.", query[:80])
            return lexical_hits
        if vector_hits and not lexical_hits:
            return vector_hits
        if not lexical_hits and not vector_hits:
            return []

        fused_items: List[Dict] = []
        for item in lexical_hits:
            payload = dict(item)
            payload["_retrieval_source"] = "offline_sqlite_lexical"
            payload["_retrieval_query"] = query
            fused_items.append(payload)
        for item in vector_hits:
            payload = dict(item)
            payload["_retrieval_source"] = "offline_lancedb_vector"
            payload["_retrieval_query"] = query
            fused_items.append(payload)

        fused = _apply_rrf_fusion(fused_items)
        for item in fused:
            item["source"] = "offline_db"
        fused = fused[:max_results]
        if fused:
            log.info(
                "Offline hybrid lexical+vector search for '%s' found %s fused items (lexical=%s vector=%s).",
                query[:80],
                len(fused),
                len(lexical_hits),
                len(vector_hits),
            )
        return fused

    def _paper_cache_keys(self, paper: Dict) -> List[str]:
        ids = paper.get("ids", {}) or {}
        keys: List[str] = []
        for prefix, value in (
            ("doi", ids.get("doi") or paper.get("doi") or ""),
            ("pmcid", ids.get("pmcid") or ""),
            ("pmid", ids.get("pmid") or ""),
            ("pdf", paper.get("pdf_url") or ""),
            ("url", paper.get("url") or ""),
            ("title", norm_title(paper.get("title", ""))),
        ):
            value = str(value or "").strip()
            if value:
                keys.append(f"{prefix}:{value}")
        return _dedupe_strings(keys)

    def _load_fulltext_cache(self, paper: Dict) -> bool:
        for key in self._paper_cache_keys(paper):
            cached = self._read_json_cache(self._fulltext_cache_dir, key)
            if not cached:
                continue
            full_text = str(cached.get("full_text") or "")
            if not full_text:
                continue
            paper["full_text"] = full_text
            paper["has_fulltext"] = bool(cached.get("has_fulltext", True))
            if cached.get("sections") is not None:
                paper["sections"] = cached.get("sections") or []
            if cached.get("tables") is not None:
                paper["tables"] = cached.get("tables") or []
            if cached.get("figures") is not None:
                paper["figures"] = cached.get("figures") or []
            if cached.get("pdf_url") and not paper.get("pdf_url"):
                paper["pdf_url"] = cached.get("pdf_url")
            if cached.get("cache_origin"):
                paper["cache_origin"] = cached.get("cache_origin")
            return True
        return False

    def _store_fulltext_cache(self, paper: Dict, *, cache_origin: str = "") -> None:
        full_text = str(paper.get("full_text") or "")
        if not full_text:
            return
        payload = {
            "full_text": full_text,
            "has_fulltext": bool(paper.get("has_fulltext", True)),
            "sections": paper.get("sections") or [],
            "tables": paper.get("tables") or [],
            "figures": paper.get("figures") or [],
            "pdf_url": paper.get("pdf_url") or "",
            "cache_origin": cache_origin,
            "saved_at": int(time.time()),
        }
        for key in self._paper_cache_keys(paper):
            self._write_json_cache(self._fulltext_cache_dir, key, payload)

    # ---- API for nodes to seed the current run dir (env-free, thread/async safe)
    @staticmethod
    def set_session_dir(path: Optional[str]) -> None:
        _SESSION_DIR_CVAR.set(path)

    # ---------------- Entrez Helpers ----------------
    def _init_entrez(self) -> None:
        if Entrez is None:
            raise RuntimeError("Bio.Entrez not available. Install Biopython.")
        try:
            Entrez.email = self._entrez_email
            Entrez.api_key = os.environ.get("NCBI_API_KEY", None)
        except Exception:
            pass

    def _entrez_fetch_and_parse(self, func, description: str, *args, **kwargs):
        global _LAST_ENTREZ_CALL
        self._init_entrez()
        last_err = None
        for attempt in range(1, self._max_retries + 1):
            handle = None
            try:
                # Apply rate limit lock across all threads
                with _ENTREZ_LOCK:
                    now = time.time()
                    elapsed = now - _LAST_ENTREZ_CALL
                    if elapsed < ENTREZ_RATE_LIMIT:
                        time.sleep(ENTREZ_RATE_LIMIT - elapsed)
                    _LAST_ENTREZ_CALL = time.time()
                    
                    handle = func(*args, **kwargs)
                    raw_content = handle.read()
                    
                if not raw_content:
                    last_err = ValueError("Empty response returned by Entrez")
                    log.warning(f"Entrez error {description} (attempt {attempt}/{self._max_retries}): empty response")
                    time.sleep(self._backoff_base ** (attempt - 1))
                    continue
                try:
                    parsed = Entrez.read(io.BytesIO(raw_content))
                    return parsed
                except Exception as exc:
                    last_err = exc
                    log.warning(f"Entrez XML parse error {description} (attempt {attempt}/{self._max_retries}): {exc}")
                    time.sleep(self._backoff_base ** (attempt - 1))
            except Exception as exc:
                last_err = exc
                log.warning(f"Entrez network error {description} (attempt {attempt}/{self._max_retries}): {exc}")
                sleep_time = (self._backoff_base ** attempt) + (random.random() * 0.5)
                if "429" in str(exc):
                    sleep_time += 5  # Extra penalty for rate limits
                time.sleep(sleep_time)
                continue
            finally:
                if handle is not None and hasattr(handle, "close"):
                    try: handle.close()
                    except Exception: pass
        if last_err:
            raise last_err
        raise RuntimeError(f"Entrez {description} failed without explicit error")

    def _entrez_get_bytes(self, func, description: str, *args, **kwargs) -> bytes:
        global _LAST_ENTREZ_CALL
        self._init_entrez()
        last_err = None
        for attempt in range(1, self._max_retries + 1):
            handle = None
            try:
                # Apply rate limit lock across all threads
                with _ENTREZ_LOCK:
                    now = time.time()
                    elapsed = now - _LAST_ENTREZ_CALL
                    if elapsed < ENTREZ_RATE_LIMIT:
                        time.sleep(ENTREZ_RATE_LIMIT - elapsed)
                    _LAST_ENTREZ_CALL = time.time()
                    
                    handle = func(*args, **kwargs)
                    raw = handle.read()
                    
                if not raw:
                    last_err = ValueError("Empty response returned by Entrez")
                    log.warning(f"Entrez empty response {description} (attempt {attempt}/{self._max_retries})")
                    time.sleep(self._backoff_base ** (attempt - 1))
                    continue
                return raw
            except Exception as exc:
                last_err = exc
                log.warning(f"Entrez network error {description} (attempt {attempt}/{self._max_retries}): {exc}")
                sleep_time = (self._backoff_base ** attempt) + (random.random() * 0.5)
                if "429" in str(exc):
                    sleep_time += 5
                time.sleep(sleep_time)
                continue
            finally:
                if handle is not None and hasattr(handle, "close"):
                    try: handle.close()
                    except Exception: pass
        if last_err:
            raise last_err
        raise RuntimeError(f"Entrez {description} failed without explicit error")

    # ---------------- PubMed / PMC ----------------
    def search_pubmed_pmc(self, query: str, max_results: int, min_date: Optional[str] = None, max_date: Optional[str] = None) -> List[Dict]:
        results: List[Dict] = []
        try:
            q_term = query

            # Add date range to query if specified
            if min_date or max_date:
                mindate_str = min_date.replace("/", "") if min_date else ""
                maxdate_str = max_date.replace("/", "") if max_date else ""
                
                search = self._entrez_fetch_and_parse(
                    Entrez.esearch, "during esearch(pubmed)",
                    db="pubmed", term=q_term, retmax=max_results, sort="relevance",
                    mindate=mindate_str, maxdate=maxdate_str, datetype="pdat",
                )
            else:
                search = self._entrez_fetch_and_parse(
                    Entrez.esearch, "during esearch(pubmed)",
                    db="pubmed", term=q_term, retmax=max_results, sort="relevance",
                )
            pmids = []
            if isinstance(search, dict):
                pmids = search.get("IdList", []) or search.get("Idlist", []) or []
            pmids = [str(x) for x in pmids if x]
            log.info(f"PubMed search for '{q_term}' found {len(pmids)} PMIDs: {pmids[:10]}...")
            if not pmids:
                return results

            # Batch fetch details (chunked to avoid URL length limits)
            chunk_size = 100
            for i in range(0, len(pmids), chunk_size):
                chunk = pmids[i:i+chunk_size]
                try:
                    fetch_res = self._entrez_fetch_and_parse(
                        Entrez.efetch, f"during efetch(pubmed) batch {i}",
                        db="pubmed", id=",".join(chunk), retmode="xml",
                    )
                    
                    articles = []
                    if isinstance(fetch_res, dict):
                        articles = fetch_res.get("PubmedArticle", [])
                    elif isinstance(fetch_res, list):
                        articles = fetch_res
                    
                    for art in articles:
                        medline = art.get("MedlineCitation", {})
                        article = medline.get("Article", {})
                        
                        pmid = str(medline.get("PMID", ""))
                        title = article.get("ArticleTitle", "")
                        
                        # Journal
                        journal_info = article.get("Journal", {})
                        jname = journal_info.get("Title") or journal_info.get("ISOAbbreviation") or ""
                        
                        # PubDate
                        pub_date_info = journal_info.get("JournalIssue", {}).get("PubDate", {})
                        pubdate = f"{pub_date_info.get('Year','')}-{pub_date_info.get('Month','')}-{pub_date_info.get('Day','')}"
                        pubdate = re.sub(r"-+", "-", pubdate).strip("-")
                        
                        # Authors
                        authors = article.get("AuthorList", [])
                        author_names = []
                        for a in authors:
                            if "LastName" in a and "ForeName" in a:
                                author_names.append(f"{a['LastName']} {a['ForeName']}")
                            elif "LastName" in a:
                                author_names.append(a["LastName"])
                        author_str = ", ".join(author_names[:3]) + (" et al." if len(author_names) > 3 else "")
                        
                        # Abstract
                        abstract_list = article.get("Abstract", {}).get("AbstractText", [])
                        abstract = " ".join([str(x) for x in abstract_list]) if abstract_list else ""
                        
                        # IDs (DOI, PMC)
                        doi = ""
                        pmcid = ""
                        
                        # Check ELocationID for DOI
                        for eloc in article.get("ELocationID", []):
                            if getattr(eloc, "attributes", {}).get("EIdType") == "doi":
                                doi = str(eloc)
                        
                        # Check PubmedData for IDs
                        pub_data = art.get("PubmedData", {})
                        for aid in pub_data.get("ArticleIdList", []):
                            id_type = getattr(aid, "attributes", {}).get("IdType")
                            if id_type == "doi" and not doi:
                                doi = str(aid)
                            elif id_type == "pmc":
                                pmcid = str(aid)
                                if not pmcid.startswith("PMC"):
                                    pmcid = f"PMC{pmcid}"
                        
                        url = f"https://doi.org/{doi}" if doi else (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "")
                        
                        results.append({
                            "source": "PubMed",
                            "ids": {"pmid": pmid, "pmcid": pmcid},
                            "title": title,
                            "authors": author_str,
                            "journal": jname,
                            "pubdate": pubdate,
                            "doi": doi,
                            "url": url,
                            "abstract": abstract,
                            "full_text": "", # Defer to Phase 1
                            "sections": [],
                            "pdf_url": "",
                            "pdf_path": "",
                            "html_path": "",
                            "has_fulltext": False,
                        })
                        
                except Exception as e:
                    log.error(f"PubMed batch fetch error: {e}")
                    
        except Exception as e:
            log.error(f"PubMed search error: {e}")
        return results

    # ---------------- Semantic Scholar ----------------
    def search_semantic_scholar(self, query: str, max_results: int, min_date: Optional[str] = None, max_date: Optional[str] = None) -> List[Dict]:
        """
        Search Semantic Scholar Graph API for papers. 
        Uses S2_API_KEY env var if present (highly recommended for rate limits).
        """
        results: List[Dict] = []
        try:
            api_key = os.environ.get("S2_API_KEY")
            headers = {"x-api-key": api_key} if api_key else {}

            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            
            # S2 doesn't like wildcards '*' in the same way PubMed does. 
            # It often causes 500 errors for complex queries.
            # We'll strip them for S2.
            s2_query = query.replace("*", "")
            
            # Cap limit at 100 for S2 to avoid 500 errors (API max is 100)
            s2_limit = min(max_results, 100)
            
            # Date filtering (year range)
            year_param = ""
            y_min = min_date[:4] if min_date and len(min_date) >= 4 else ""
            y_max = max_date[:4] if max_date and len(max_date) >= 4 else ""
            
            if y_min and y_max:
                year_param = f"{y_min}-{y_max}"
            elif y_min:
                year_param = f"{y_min}-"
            elif y_max:
                year_param = f"-{y_max}"

            # We request openAccessPdf to get direct PDF links
            params = {
                "query": s2_query,
                "limit": s2_limit,
                "fields": "paperId,title,authors,year,venue,externalIds,isOpenAccess,openAccessPdf,abstract,publicationDate,publicationTypes"
            }
            if year_param:
                params["year"] = year_param

            request_params = dict(params)
            r = None
            for attempt in range(1, FULLTEXT_S2_MAX_RETRIES + 1):
                self._semantic_scholar_rate_limit_wait(bool(api_key))
                r = self._http.get(url, headers=headers, params=request_params, timeout=30)
                if r.status_code != 429:
                    break
                backoff_s = min(30.0, (2 ** (attempt - 1)) + random.uniform(0.5, 1.5))
                log.warning(
                    "Semantic Scholar 429 (attempt %d/%d). Backing off %.1fs...",
                    attempt,
                    FULLTEXT_S2_MAX_RETRIES,
                    backoff_s,
                )
                time.sleep(backoff_s)

            if r is None:
                return results
            
            if 500 <= r.status_code < 600:
                log.warning(f"Semantic Scholar server error {r.status_code}. Retrying with simplified query...")
                time.sleep(2)
                # Simplify query: remove boolean operators and parentheses, just keep words
                # This is a drastic simplification but often necessary for S2 to not crash on complex queries
                simple_query = re.sub(r'[()"]', '', s2_query)
                simple_query = re.sub(r'\b(AND|OR|NOT)\b', ' ', simple_query)
                simple_query = re.sub(r'\s+', ' ', simple_query).strip()
                log.info(f"Retrying S2 with simplified query: '{simple_query}'")
                
                request_params["query"] = simple_query
                self._semantic_scholar_rate_limit_wait(bool(api_key))
                r = self._http.get(url, headers=headers, params=request_params, timeout=30)

            r.raise_for_status()
            
            data = r.json()
            for item in data.get("data", []):
                paper_id = item.get("paperId", "")
                title = item.get("title", "")
                abstract = item.get("abstract") or ""
                year = item.get("year")
                venue = item.get("venue") or ""
                pub_date = item.get("publicationDate") or (str(year) if year else "")
                pub_types = item.get("publicationTypes", [])
                
                ext_ids = item.get("externalIds", {})
                doi = ext_ids.get("DOI", "")
                pmid = ext_ids.get("PubMed", "")
                arxiv_id = ext_ids.get("ArXiv", "")
                
                # Authors
                authors_list = item.get("authors", [])
                author_names = [a.get("name", "") for a in authors_list]
                author_str = ", ".join(author_names[:3]) + (" et al." if len(author_names) > 3 else "")
                
                # PDF URL
                pdf_url = ""
                oa_pdf = item.get("openAccessPdf")
                if oa_pdf and isinstance(oa_pdf, dict):
                    pdf_url = oa_pdf.get("url", "")
                
                # If no PDF from S2, but we have ArXiv ID, construct it
                if not pdf_url and arxiv_id:
                    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

                results.append({
                    "source": "SemanticScholar",
                    "ids": {"s2id": paper_id, "doi": doi, "pmid": pmid, "arxiv": arxiv_id},
                    "title": title,
                    "authors": author_str,
                    "journal": venue,
                    "pubdate": pub_date,
                    "publication_types": pub_types,
                    "doi": doi,
                    "url": item.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}",
                    "abstract": abstract,
                    "pdf_url": pdf_url,
                    "full_text": "",
                    "sections": [],
                    "has_fulltext": False,
                })
                
        except Exception as e:
            log.error(f"Semantic Scholar search error: {e}")
        
        return results

    # ---------------- Europe PMC (search + JATS fullTextXML) ----------------
    def search_eupmc(self, query: str, max_results: int, min_date: Optional[str] = None, max_date: Optional[str] = None) -> List[Dict]:
        results: List[Dict] = []
        try:
            # Build date range filter for Europe PMC
            q_term = query
            if min_date or max_date:
                # Europe PMC uses FIRST_PDATE:[mindate TO maxdate] format
                mindate_eupmc = min_date.replace("/", "-") if min_date else "*"
                maxdate_eupmc = max_date.replace("/", "-") if max_date else "*"
                q_term = f"({query}) AND FIRST_PDATE:[{mindate_eupmc} TO {maxdate_eupmc}]"
            
            url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            params = {"query": q_term, "format": "json", "pageSize": min(1000, max_results), "resultType": "core"}
            r = self._http.get(url, params=params, timeout=30); r.raise_for_status()
            data = r.json()
            for rec in (data.get("resultList", {}).get("result", []) or [])[:max_results]:
                doi   = (rec.get("doi") or "").strip()
                pmid  = (rec.get("pmid") or "").strip()
                pmcid = (rec.get("pmcid") or "").strip()
                src   = (rec.get("source") or "").strip()  # e.g., MEDRXIV, CHEMRXIV, PMCID, AGR
                title = rec.get("title","") or ""
                author_str = rec.get("authorString","") or ""
                journal = rec.get("journalTitle","") or rec.get("bookOrReportDetails","") or ""
                pubdate = (rec.get("firstPublicationDate") or rec.get("pubYear",""))[:10]
                pdf_url = ""
                for u in (rec.get("fullTextUrlList", {}) or {}).get("fullTextUrl", []) or []:
                    if u.get("documentStyle") == "pdf" and u.get("availability") in {"Open access","Open","Free"}:
                        pdf_url = u.get("url",""); break
                results.append({
                    "source": f"EuropePMC:{src or 'article'}",
                    "ids": {"doi": doi, "pmid": pmid, "pmcid": pmcid, "eupmc_id": rec.get("id","")},
                    "title": title,
                    "authors": author_str,
                    "journal": journal,
                    "pubdate": pubdate,
                    "doi": doi,
                    "url": rec.get("url","") or (f"https://europepmc.org/article/{src}/{rec.get('id')}" if src and rec.get("id") else ""),
                    "abstract": rec.get("abstractText","") or "",
                    "pdf_url": pdf_url,
                    "full_text": "",
                    "sections": [],
                    "has_fulltext": False,
                    "xml_url": "",  # attempt via fullTextXML next
                })
        except Exception as e:
            log.error(f"Europe PMC search error: {e}")
        return results

    def eupmc_fulltext_jats(self, eupmc_source: str, eupmc_id: str) -> Tuple[str, List[Dict[str,str]], Optional[str]]:
        if not eupmc_source or not eupmc_id:
            return "", [], None
        base = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        xml_url = f"{base}/{eupmc_source}/{eupmc_id}/fullTextXML"
        try:
            r = self._http.get(xml_url, timeout=60)
            if r.status_code == 404:
                return "", [], None
            r.raise_for_status()
            xml_path = None
            assets_dir = self._get_effective_assets_dir()
            if assets_dir:
                fn = sanitize_filename(f"{eupmc_source}_{eupmc_id}") + ".xml"
                fp = assets_dir / fn
                fp.write_bytes(r.content); xml_path = str(fp)
            root = ET.fromstring(r.content)
            sections = jats_nodes_to_sections(root)
            full_text = sections_to_markdown(sections)
            return full_text, sections, xml_path
        except Exception as e:
            log.debug(f"Europe PMC fullTextXML fetch/parse failed for {eupmc_source}:{eupmc_id}: {e}")
            return "", [], None

    # ---------------- arXiv ----------------
    def _get_cross_encoder(self):
        if not self._cross_encoder and CrossEncoder:
            try:
                device = FULLTEXT_RERANK_DEVICE or ("cuda" if torch.cuda.is_available() else "cpu")
                self._cross_encoder = CrossEncoder(FULLTEXT_RERANK_MODEL, device=device)
                log.info(f"Loaded paper reranker: {FULLTEXT_RERANK_MODEL} on {device}")
            except Exception as e:
                log.warning(f"Failed to load cross-encoder '{FULLTEXT_RERANK_MODEL}': {e}")
                if FULLTEXT_RERANK_FALLBACK_MODEL and FULLTEXT_RERANK_FALLBACK_MODEL != FULLTEXT_RERANK_MODEL:
                    try:
                        device = FULLTEXT_RERANK_DEVICE or ("cuda" if torch.cuda.is_available() else "cpu")
                        self._cross_encoder = CrossEncoder(FULLTEXT_RERANK_FALLBACK_MODEL, device=device)
                        log.info(f"Loaded fallback paper reranker: {FULLTEXT_RERANK_FALLBACK_MODEL} on {device}")
                    except Exception as fallback_error:
                        log.warning(f"Failed to load fallback cross-encoder '{FULLTEXT_RERANK_FALLBACK_MODEL}': {fallback_error}")
        return self._cross_encoder

    def _rerank_results(
        self,
        query: str | List[str],
        papers: List[Dict],
    ) -> List[Dict]:
        """
        Rerank papers using Cross-Encoder.
        Supports Multi-Query: If query is a list, computes score for each query and takes the MAX score per paper.
        """
        model = self._get_cross_encoder()
        if not model or not papers:
            return papers

        # Normalize query to list
        queries = []
        if isinstance(query, list):
            queries = [str(q).strip() for q in query if q and str(q).strip()]
        elif isinstance(query, str) and query.strip():
            queries = [query.strip()]
            
        if not queries:
            return papers

        # Prepare paper texts once
        paper_texts = []
        valid_indices = []
        for idx, p in enumerate(papers):
            title = p.get("title")
            if title is None: title = ""
            elif not isinstance(title, str): title = str(title)
            
            abstract = p.get("abstract")
            if abstract is None: abstract = ""
            elif not isinstance(abstract, str): abstract = str(abstract)
            
            # Fallback for empty abstract
            if not abstract and p.get("full_text"):
                 # Use start of full text if abstract missing
                 abstract = str(p.get("full_text"))[:500]

            text = f"{title}. {abstract}".strip()
            if not text: text = "Empty" # Avoid empty string issues
            
            paper_texts.append(text)
            valid_indices.append(idx)

        if not paper_texts:
            return papers

        # Initialize max scores
        # Default to very low score
        final_scores = [-999.0] * len(papers)

        for q in queries:
            pairs = [[q, text] for text in paper_texts]
            
            try:
                log.info(f"Reranking {len(pairs)} papers for query '{q[:30]}...'")
                scores = model.predict(pairs)
                
                for i, score in enumerate(scores):
                    # Update max score
                    current_idx = valid_indices[i]
                    title = papers[current_idx].get("title") or ""
                    abstract = papers[current_idx].get("abstract") or ""
                    model_score = float(score)
                    if model_score > final_scores[current_idx]:
                        final_scores[current_idx] = model_score
                        
            except Exception as e:
                log.warning(f"Reranking failed for query '{q}': {e}")
                continue

        # Assign final scores
        for i, idx in enumerate(valid_indices):
            # Only assign if we got a valid score (greater than init)
            if final_scores[idx] > -900.0:
                papers[idx]["_relevance_score"] = final_scores[idx]
            else:
                # If all failed or no update, leave as 0 or keep original order
                # But safer to assign something low to keep it sortable
                papers[idx]["_relevance_score"] = -100.0

        # Sort primarily by model score. Use identity match and retrieval consensus only as
        # retrieval-consensus tie-breakers after the model score.
        papers.sort(
            key=lambda x: (
                round(float(x.get("_relevance_score", -100.0)), 2),
                int(x.get("_rrf_hits", 0)),
                bool(x.get("has_fulltext")),
                float(x.get("_rrf_score", 0.0)),
            ),
            reverse=True,
        )
        log.info("Reranking complete.")
            
        return papers

    def search_arxiv(self, query: str, max_results: int) -> List[Dict]:
        if not query:
            return []
        results: List[Dict] = []
        try:
            url = "http://export.arxiv.org/api/query"
            params = {
                "search_query": f'all:"{query}"',
                "start": 0, "max_results": max_results,
                "sortBy": "relevance", "sortOrder": "descending",
            }
            r = self._http.get(url, params=params, timeout=30); r.raise_for_status()
            root = ET.fromstring(r.content); ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns):
                title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip().replace("\n"," ")
                abstract = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
                pub_date = entry.findtext("atom:published", default="", namespaces=ns) or ""
                pubdate = pub_date[:10] if pub_date else ""
                arxiv_id = entry.findtext("atom:id", default="", namespaces=ns) or ""
                authors = [a.findtext("atom:name", default="", namespaces=ns) or "" for a in entry.findall("atom:author", ns)]
                author_str = ", ".join([a for a in authors if a][:3]) + (" et al." if len(authors) > 3 else "")

                pdf_url = ""
                for link in entry.findall("atom:link", ns):
                    rel = link.attrib.get("rel",""); href = link.attrib.get("href",""); title_attr = link.attrib.get("title","")
                    if title_attr and title_attr.lower() == "pdf":
                        pdf_url = href
                    elif (rel == "related" and href.endswith(".pdf")):
                        pdf_url = href
                if not pdf_url and arxiv_id:
                    m = re.search(r"arxiv.org/abs/(\S+)", arxiv_id)
                    if m: pdf_url = f"https://arxiv.org/pdf/{m.group(1)}.pdf"

                results.append({
                    "source": "arXiv",
                    "ids": {"arxiv": arxiv_id},
                    "title": title,
                    "authors": author_str,
                    "journal": "arXiv preprint",
                    "pubdate": pubdate,
                    "doi": "",
                    "url": arxiv_id,
                    "abstract": abstract,
                    "pdf_url": pdf_url,
                    "full_text": "",
                    "sections": [],
                    "pdf_path": "",
                    "html_path": "",
                    "has_fulltext": False,
                })
        except requests.exceptions.HTTPError as e:
            if e.response.status_code >= 500:
                log.warning(f"arXiv server error (skipping): {e}")
            else:
                log.error(f"arXiv search error: {e}")
        except Exception as e:
            log.error(f"arXiv search error: {e}")
        return results

    # ---------------- medRxiv ----------------
    def search_medrxiv(self, query: str, max_results: int) -> List[Dict]:
        results: List[Dict] = []
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=3*365)
            url = f"https://api.medrxiv.org/details/medrxiv/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
            r = self._http.get(url, timeout=60); r.raise_for_status()
            data = r.json()
            if not (data.get("messages") and data["messages"][0].get("status") == "ok"):
                return results

            ql = (query or "").lower()
            for p in data.get("collection", []):
                title = p.get("title","") or ""; abstract = p.get("abstract","") or ""
                if ql and (ql not in title.lower() and ql not in abstract.lower()):
                    continue

                doi = (p.get("doi") or "").strip()
                version = str(p.get("version") or "").strip()
                if not doi:
                    continue

                base = f"https://www.medrxiv.org/content/{doi}"
                landing = f"{base}v{version}" if version else base

                pub_date = p.get("date", "")
                if pub_date and len(pub_date) >= 10:
                    year, month, day = pub_date[:4], pub_date[5:7], pub_date[8:10]
                    doi_part = doi.replace("10.1101/", "")
                    xml_url = f"https://www.medrxiv.org/content/medrxiv/early/{year}/{month}/{day}/{doi_part}.source.xml"
                else:
                    xml_url = f"{landing}.source.xml"

                html_url = f"{landing}.full"
                pdf_url  = f"{landing}.full.pdf"

                authors_raw = p.get("authors","") or ""
                author_list = []
                for a in [x.strip() for x in authors_raw.split(";") if x.strip()]:
                    if "," in a:
                        last, first = a.split(",",1); author_list.append(f"{first.strip()} {last.strip()}")
                    else:
                        author_list.append(a)
                author_str = ", ".join(author_list[:3]) + (" et al." if len(author_list) > 3 else "")

                results.append({
                    "source": "medRxiv",
                    "ids": {"doi": doi, "version": version},
                    "title": title,
                    "authors": author_str,
                    "journal": "medRxiv preprint",
                    "pubdate": p.get("date","") or "",
                    "doi": doi,
                    "url": landing,
                    "abstract": abstract,
                    "xml_url": xml_url,
                    "html_url": html_url,
                    "pdf_url": pdf_url,
                    "full_text": "",
                    "sections": [],
                    "pdf_path": "",
                    "html_path": "",
                    "has_fulltext": False,
                })
                if len(results) >= max_results:
                    break
        except Exception as e:
            log.error(f"medRxiv search error: {e}")
        return results

    # ---------------- ChemRxiv via Figshare ----------------
    def search_chemrxiv_via_figshare(self, query: str, max_results: int) -> List[Dict]:
        results: List[Dict] = []
        try:
            q = query or ""
            url = f"https://api.figshare.com/v2/collections/3997422/articles?search_for={q}&page_size={min(100, max_results)}"
            r = self._http.get(url, timeout=60); r.raise_for_status()
            data = r.json()
            for item in data[:max_results]:
                title = item.get("title", "") or ""
                doi = item.get("doi", "") or ""
                published_date = (item.get("published_date") or "")[:10]
                article_id = item.get("id")
                pdf_url = ""
                if article_id:
                    try:
                        article_url = f"https://api.figshare.com/v2/articles/{article_id}"
                        r2 = self._http.get(article_url, timeout=60)
                        if r2.status_code == 200:
                            article_data = r2.json()
                            files = article_data.get("files", [])
                            for f in files:
                                if f.get("name", "").lower().endswith(".pdf"):
                                    pdf_url = f.get("download_url", "")
                                    break
                    except Exception:
                        pass

                results.append({
                    "source": "ChemRxiv",
                    "ids": {"doi": doi},
                    "title": title,
                    "authors": "",
                    "journal": "ChemRxiv preprint",
                    "pubdate": published_date,
                    "doi": doi,
                    "url": item.get("url_public_html", ""),
                    "abstract": "",
                    "xml_url": "",
                    "html_url": "",
                    "pdf_url": pdf_url,
                    "full_text": "",
                    "sections": [],
                    "pdf_path": "",
                    "html_path": "",
                    "has_fulltext": False,
                })
        except Exception as e:
            log.error(f"ChemRxiv (Figshare) search error for '{query}': {e}")
        return results

    # ---------------- Unpaywall (DOI → best OA location) ----------------
    def unpaywall_lookup(self, doi: str, email: str = "you@example.com") -> Tuple[str, str]:
        if not doi:
            return "", ""
        try:
            r = self._http.get(f"https://api.unpaywall.org/v2/{doi}", params={"email": email}, timeout=30)
            if r.status_code == 404:
                return "", ""
            r.raise_for_status()
            u = r.json()
            loc = u.get("best_oa_location") or {}
            pdf = (loc.get("url_for_pdf") or "") or ""
            landing = loc.get("url") or ""
            return pdf, landing
        except Exception as e:
            log.debug(f"Unpaywall lookup failed for {doi}: {e}")
            return "", ""

    # ---------------- Fetchers & Parsers (fallback helpers) ----------------
    def download_to_path(self, url: str, path: pathlib.Path) -> bool:
        key = self._download_failure_key(url)
        now = time.time()
        if key:
            until = self._download_circuit_until.get(key, 0.0)
            if until > now:
                wait_s = int(until - now)
                log.warning(f"[PDF Circuit Open] Skipping download for key={key} ({wait_s}s remaining): {url[:120]}")
                return False

        try:
            # Fail fast for slow/blocked publisher endpoints.
            # Default: one-shot raw requests (no urllib3 retry loop) + circuit breaker.
            # Optional fallback to retry-enabled session can be enabled via env.
            use_retry_session = FULLTEXT_PDF_DOWNLOAD_USE_RETRY_SESSION
            getter = self._http.get if use_retry_session else requests.get
            req_kwargs = {
                "timeout": (FULLTEXT_PDF_DOWNLOAD_CONNECT_TIMEOUT, FULLTEXT_PDF_DOWNLOAD_READ_TIMEOUT),
                "stream": True,
                "headers": {"User-Agent": "Enhanced-Journal-Search/2.0 (mailto: laozc@student.ubc.ca)"},
            }
            with getter(url, **req_kwargs) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if chunk: f.write(chunk)
            if key:
                self._download_fail_counts.pop(key, None)
                self._download_circuit_until.pop(key, None)
            return True
        except Exception as e:
            if key:
                count = int(self._download_fail_counts.get(key, 0)) + 1
                self._download_fail_counts[key] = count
                if count >= FULLTEXT_PDF_FAIL_CIRCUIT_THRESHOLD:
                    self._download_circuit_until[key] = time.time() + FULLTEXT_PDF_FAIL_CIRCUIT_SECONDS
                    log.warning(
                        f"[PDF Circuit Trip] key={key}, failures={count}, open_for={FULLTEXT_PDF_FAIL_CIRCUIT_SECONDS}s, url={url[:120]}"
                    )
            log.debug(f"Download failed {url}: {e}")
            return False

    def _download_failure_key(self, url: str) -> str:
        if not url:
            return ""
        m = re.search(r"(PMC\d+)", url, flags=re.IGNORECASE)
        if m:
            return m.group(1).upper()
        if "ptpmcrender.fcgi" in url:
            return "ptpmcrender"
        try:
            from urllib.parse import urlparse
            u = urlparse(url)
            host = (u.netloc or "").lower()
            path = (u.path or "").lower()
            if host:
                return f"{host}:{path[:120]}"
        except Exception:
            pass
        return ""

    def _semantic_scholar_rate_limit_wait(self, has_api_key: bool) -> None:
        min_interval = FULLTEXT_S2_MIN_INTERVAL_WITH_KEY if has_api_key else FULLTEXT_S2_MIN_INTERVAL_NO_KEY
        lock_path = "/tmp/fulltext_s2_rate_limit.lock"
        ts_path = "/tmp/fulltext_s2_rate_limit.ts"
        try:
            with open(lock_path, "w", encoding="utf-8") as lockf:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
                last_ts = 0.0
                if os.path.exists(ts_path):
                    try:
                        with open(ts_path, "r", encoding="utf-8") as tsf:
                            last_ts = float((tsf.read() or "0").strip() or "0")
                    except Exception:
                        last_ts = 0.0
                now = time.time()
                wait_s = (last_ts + min_interval) - now
                if wait_s > 0:
                    time.sleep(wait_s)
                now = time.time()
                with open(ts_path, "w", encoding="utf-8") as tsf:
                    tsf.write(str(now))
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
        except Exception:
            # Fallback if lock/state-file operations fail.
            time.sleep(min_interval + random.uniform(0, 0.4))
    
    def is_valid_pdf(self, file_path: pathlib.Path) -> bool:
        """Check if the downloaded file is a valid PDF by reading its magic number."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(5)
                if header == b'%PDF-':
                    return True
                else:
                    log.warning(f"File {file_path.name} is not a valid PDF (likely an HTML error page).")
                    return False
        except Exception as e:
            log.warning(f"Failed to check PDF validity for {file_path.name}: {e}")
            return False

    def _extract_cached_or_local_pdf(self, paper: dict, local_pdf_path: pathlib.Path) -> dict:
        if self._load_fulltext_cache(paper):
            paper["has_fulltext"] = True
            return paper

        extracted = self._extract_with_opendataloader(local_pdf_path)
        if extracted:
            cleaned = self.clean_extracted_text(extracted, source="opendataloader")
            paper.update({"full_text": cleaned or extracted, "has_fulltext": True})
            self._store_fulltext_cache(paper, cache_origin="opendataloader_single")
            return paper

        txt, tables, figures = self.pdf_to_text_tables_figures(local_pdf_path, local_pdf_path.parent)
        cleaned = self.clean_extracted_text(txt)
        if cleaned:
            paper.update({"full_text": cleaned, "tables": tables, "figures": figures, "has_fulltext": True})
            self._store_fulltext_cache(paper, cache_origin="pdfminer_single")
        return paper

    def pdf_to_text_tables_figures(self, pdf_path: pathlib.Path, assets_dir: pathlib.Path) -> Tuple[str, List[Dict], List[str]]:
        try:
            text = pdf_extract_text(str(pdf_path)) or ""
            return text, [], []
        except Exception as e:
            log.debug(f"PDF text extraction failed {pdf_path}: {e}")
            return "", [], []

    def _extract_with_opendataloader(self, pdf_path: pathlib.Path) -> str:
        try:
            import opendataloader_pdf  # type: ignore
        except Exception as e:
            log.warning(f"[OpenDataLoader] Package unavailable ({e}). Falling back to docling/pdfminer.")
            return ""

        out_dir = pdf_path.parent / f"odl_{pdf_path.stem}"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            # Use the single package `opendataloader-pdf[hybrid]` when configured.
            convert_kwargs: Dict[str, Any] = {
                "input_path": [str(pdf_path)],
                "output_dir": str(out_dir),
                "format": "markdown",
                "quiet": True,
            }
            if self.odl_use_hybrid:
                convert_kwargs["hybrid"] = self.odl_hybrid_model or "docling-fast"
                if self.odl_hybrid_mode:
                    convert_kwargs["hybrid_mode"] = self.odl_hybrid_mode
                if self.odl_hybrid_url:
                    convert_kwargs["hybrid_url"] = self.odl_hybrid_url
                if self.odl_hybrid_timeout:
                    convert_kwargs["hybrid_timeout"] = self._normalize_odl_hybrid_timeout(self.odl_hybrid_timeout)
                convert_kwargs["hybrid_fallback"] = self.odl_hybrid_fallback
            try:
                self._run_opendataloader_convert(convert_kwargs)
            except Exception as e:
                if self.odl_use_hybrid and self.odl_hybrid_fallback:
                    log.warning(f"[OpenDataLoader] Hybrid conversion failed for {pdf_path.name}; retrying in local mode: {e}")
                    local_kwargs = dict(convert_kwargs)
                    local_kwargs.pop("hybrid", None)
                    local_kwargs.pop("hybrid_mode", None)
                    local_kwargs.pop("hybrid_url", None)
                    local_kwargs.pop("hybrid_timeout", None)
                    local_kwargs.pop("hybrid_fallback", None)
                    self._run_opendataloader_convert(local_kwargs)
                else:
                    raise
            md_files = sorted(out_dir.rglob("*.md"))
            if not md_files:
                log.warning(f"[OpenDataLoader] No markdown output for {pdf_path.name}")
                return ""
            text = md_files[0].read_text(encoding="utf-8", errors="ignore")
            cleaned = self.clean_extracted_text(text)
            if cleaned:
                log.info(f"[OpenDataLoader OK] {pdf_path.name} -> {md_files[0].name}")
            return cleaned
        except Exception as e:
            log.warning(f"[OpenDataLoader FAIL] {pdf_path.name}: {e}")
            return ""

    def _build_opendataloader_cli_args(self, convert_kwargs: Dict[str, Any]) -> List[str]:
        args: List[str] = []
        input_path = convert_kwargs.get("input_path")
        if isinstance(input_path, list):
            args.extend(str(x) for x in input_path)
        elif input_path:
            args.append(str(input_path))

        mapping = [
            ("output_dir", "--output-dir"),
            ("password", "--password"),
            ("hybrid", "--hybrid"),
            ("hybrid_mode", "--hybrid-mode"),
            ("hybrid_url", "--hybrid-url"),
            ("hybrid_timeout", "--hybrid-timeout"),
            ("table_method", "--table-method"),
            ("reading_order", "--reading-order"),
            ("image_output", "--image-output"),
            ("image_format", "--image-format"),
            ("image_dir", "--image-dir"),
            ("pages", "--pages"),
        ]
        format_value = convert_kwargs.get("format")
        if format_value:
            if isinstance(format_value, list):
                args.extend(["--format", ",".join(str(x) for x in format_value if x)])
            else:
                args.extend(["--format", str(format_value)])
        if convert_kwargs.get("quiet"):
            args.append("--quiet")
        if convert_kwargs.get("hybrid_fallback"):
            args.append("--hybrid-fallback")
        for key, flag in mapping:
            value = convert_kwargs.get(key)
            if value:
                args.extend([flag, str(value)])
        return args

    def _run_opendataloader_convert(self, convert_kwargs: Dict[str, Any]) -> None:
        """
        Run the bundled OpenDataLoader CLI with a hard timeout so a single bad PDF
        cannot stall the whole upper-stream run.
        """
        timeout_s = max(1, int(FULLTEXT_ODL_CONVERT_TIMEOUT_SECONDS))
        jar_ref = resources.files("opendataloader_pdf").joinpath("jar", "opendataloader-pdf-cli.jar")
        with resources.as_file(jar_ref) as jar_path:
            command = ["java", "-jar", str(jar_path), *self._build_opendataloader_cli_args(convert_kwargs)]
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding=locale.getpreferredencoding(False),
                start_new_session=True,
            )
            try:
                output, _ = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    proc.kill()
                try:
                    output, _ = proc.communicate(timeout=5)
                except Exception:
                    output = ""
                raise TimeoutError(
                    f"OpenDataLoader timed out after {timeout_s}s for "
                    f"{convert_kwargs.get('input_path')}"
                )
            if proc.returncode:
                raise subprocess.CalledProcessError(proc.returncode, command, output=output)

    def clean_extracted_text(self, text: str, source: str = "") -> str:
        if not text:
            return ""
        t = _normalize_flat_text(text)
        t = re.sub(r"\r", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        t = re.sub(r"^\s*\d{1,3}\s*$", "", t, flags=re.M)
        # Repair line/page number fragments injected into hyphenated names in PDF text,
        # e.g. "N,2- - 786 Dichloroacetamide" -> "N,2-Dichloroacetamide".
        t = re.sub(r"(?<=[A-Za-z0-9])\s*-\s*-\s*\d{1,4}\s+(?=[A-Za-z])", "-", t)
        t = re.sub(r"(?<=[A-Za-z0-9])\s*-\s*\d{1,4}\s+(?=[A-Za-z])", "-", t)
        t = re.sub(r"(?<=\s)-\s*\d{1,4}(?=\s)", "", t)
        # Repair split hyphenated chemical tokens left by PDF extraction, e.g.
        # "1-Amino- 1carboxycyclohexane" -> "1-Amino-1carboxycyclohexane".
        t = re.sub(r"(?<=[A-Za-z0-9])-\s+(?=[A-Za-z0-9])", "-", t)
        # Remove likely inline footnote/link suffix markers attached to compound names
        # in table-derived PDF text, e.g.:
        #   "N,2-Dichloracetamideb 2.56 × 10-4 Kimura et al."
        #   "Chloroacetic acidb 8.10 × 10-4 Plewa et al."
        t = re.sub(
            r"(?P<name>\b[A-Z0-9][A-Za-z0-9,\-\(\)\[\]′'\"/\.]*(?:\s+[A-Za-z0-9,\-\(\)\[\]′'\"/\.]+){0,4}?)(?P<suffix>[a-d])(?=(?:\s+\d|\s+[A-Z][a-z]+(?:\s+and\s+[A-Z][a-z]+)?\s+et\s+al\.|\s+Not genotoxic|\s+High cytotoxicity))",
            r"\g<name>",
            t,
        )
        # Collapse exact duplicated hyphen-joined tokens introduced by flattened headings,
        # e.g. "N-Chloraldimines-N-Chloraldimines" -> "N-Chloraldimines".
        t = re.sub(
            r"\b(?P<term>[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+)-(?P=term)\b",
            r"\g<term>",
            t,
        )
        m = re.search(r"\n\s*(references|bibliography)\b", t, flags=re.I)
        if m:
            t = t[:m.start()].strip()
        if source.lower() in {"arxiv", "biorxiv", "medrxiv", "chemrxiv"}:
            t = re.sub(r"arXiv:\s*\S+", "", t)
            t = re.sub(r"(bioRxiv|medRxiv)\s+preprint\s+.*?doi:\s*\S+.*?$", "", t, flags=re.I|re.M)
        t = re.sub(r"[ \t]+", " ", t).strip()
        return t

    # ---------------- Docling from URL ----------------
    def docling_url_to_text(self, pdf_url: str) -> Tuple[str, List[Dict], List[str]]:
        """Use Docling to convert a PDF.
        Downloads the PDF first (in parallel, outside lock), then converts (serial, inside lock).
        """
        if not pdf_url:
            return "", [], []

        # 1. Determine local path
        assets_dir = self._get_effective_assets_dir()
        if not assets_dir:
             # Fallback to temp dir if no assets dir configured
             import tempfile
             assets_dir = pathlib.Path(tempfile.gettempdir())
        
        # Use hash of URL for filename
        fname = sanitize_filename(hashlib.md5(pdf_url.encode()).hexdigest()) + ".pdf"
        local_pdf_path = assets_dir / fname

        # 2. Download if not exists (Parallel I/O)
        # This happens outside the lock, so multiple threads can download simultaneously
        if not local_pdf_path.exists():
            if not self.download_to_path(pdf_url, local_pdf_path):
                log.warning(f"[Docling] Download failed for {pdf_url}")
                return "", [], []
        
        # Check file size (skip if > 50MB to avoid OOM/Crash)
        try:
            file_size_mb = local_pdf_path.stat().st_size / (1024 * 1024)
            if file_size_mb > 50:
                log.warning(f"[Docling] Skipping large file {fname} ({file_size_mb:.2f} MB)")
                return "", [], []
        except Exception:
            pass

        # Optional alternative extractor backend.
        if self.pdf_text_extractor == "opendataloader":
            extracted = self._extract_with_opendataloader(local_pdf_path)
            if extracted:
                cleaned = self.clean_extracted_text(extracted, source="opendataloader")
                return cleaned or extracted, [], []
            log.warning(f"[OpenDataLoader] Falling back to docling/pdfminer for {local_pdf_path.name}")

        # Chunking logic for large files
        try:
            file_size_mb = local_pdf_path.stat().st_size / (1024 * 1024)
            if file_size_mb > 10 and self._docling is not None: # Chunk files larger than 10MB
                log.info(f"[Docling] Large file detected ({file_size_mb:.2f} MB). Attempting to chunk...")
                try:
                    reader = pypdf.PdfReader(local_pdf_path)
                    total_pages = len(reader.pages)
                    chunk_size = 10
                    
                    if total_pages > chunk_size:
                        full_text_parts = []
                        for i in range(0, total_pages, chunk_size):
                            chunk_writer = pypdf.PdfWriter()
                            for j in range(i, min(i + chunk_size, total_pages)):
                                chunk_writer.add_page(reader.pages[j])
                            
                            chunk_path = local_pdf_path.parent / f"{local_pdf_path.stem}_chunk_{i}.pdf"
                            with open(chunk_path, "wb") as f:
                                chunk_writer.write(f)
                            
                            # Convert chunk
                            res = self._docling.convert(chunk_path)
                            doc = res.document
                            chunk_text = None
                            for attr in ("export_to_markdown", "to_markdown", "export_markdown"):
                                if hasattr(doc, attr):
                                    chunk_text = getattr(doc, attr)()
                                    break
                            if chunk_text is None and hasattr(res, "text"):
                                chunk_text = res.text
                            if chunk_text is None:
                                chunk_text = ""
                            
                            full_text_parts.append(chunk_text)
                            chunk_path.unlink() # Cleanup
                        
                        full_text = "\n\n".join(full_text_parts)
                        full_text = self.clean_extracted_text(full_text)
                        return full_text, [], []
                except Exception as e:
                    log.warning(f"[Docling] Chunking failed: {e}. Falling back to full file.")
        except Exception:
            pass

        # 3. Convert (Standard)
        if self._docling is not None:
            try:
                # Lock removed to allow parallel conversion if supported by hardware
                # with _DOCLING_LOCK: 
                res = self._docling.convert(local_pdf_path)
                
                if not res or not getattr(res, "document", None):
                    return "", [], []
                
                doc = res.document
                full_text = None
                for attr in ("export_to_markdown", "to_markdown", "export_markdown"):
                    if hasattr(doc, attr):
                        full_text = getattr(doc, attr)()
                        break
                if full_text is None and hasattr(res, "text"):
                    full_text = res.text
                if full_text is None and hasattr(doc, "pages"):
                    try:
                        full_text = "\n\n".join(getattr(p, "text", "") for p in doc.pages)
                    except Exception:
                        full_text = ""
                full_text = self.clean_extracted_text(full_text or "")
                return full_text, [], []
            except Exception as e:
                log.warning(f"Docling conversion failed for {local_pdf_path.name}: {e}. Falling back to pdfminer.")
                # Fallback to pdfminer if docling fails on the file
        
        # 4. Fallback to pdfminer (if docling missing or failed)
        try:
             txt, tables, figs = self.pdf_to_text_tables_figures(local_pdf_path, assets_dir)
             return self.clean_extracted_text(txt), tables, figs
        except Exception as e:
             log.debug(f"Fallback PDF extraction failed: {e}")
             return "", [], []

    # ---------------- Dedup & Save ----------------
    def deduplicate(self, items: List[Dict]) -> List[Dict]:
        seen_doi, seen_pmid, seen_s2, seen_arxiv, seen_title = set(), set(), set(), set(), []
        uniq: List[Dict] = []
        for it in items:
            ids = it.get("ids", {}) or {}
            doi = (ids.get("doi") or it.get("doi") or "").lower().strip()
            pmid = (ids.get("pmid") or "").strip()
            s2id = (ids.get("s2id") or "").strip()
            arxiv_id = (ids.get("arxiv") or "").strip()

            if doi and doi in seen_doi: continue
            if pmid and pmid in seen_pmid: continue
            if s2id and s2id in seen_s2: continue
            if arxiv_id and arxiv_id in seen_arxiv: continue

            t = it.get("title","") or ""
            if any(title_close(t, prev) for prev in seen_title): continue

            if doi: seen_doi.add(doi)
            if pmid: seen_pmid.add(pmid)
            if s2id: seen_s2.add(s2id)
            if arxiv_id: seen_arxiv.add(arxiv_id)
            seen_title.append(t)
            uniq.append(it)
        return uniq

    def save_results(self, papers: List[Dict], run_dir: pathlib.Path) -> Tuple[List[str], str, str]:
        """
        Legacy method for backward compatibility. 
        New code should use _save_batch_streaming for memory efficiency.
        """
        run_dir.mkdir(parents=True, exist_ok=True)
        index_csv, index_ndjson = run_dir / "index.csv", run_dir / "index.ndjson"
        saved_files: List[str] = []

        with index_csv.open("w", newline="", encoding="utf-8") as fcsv, index_ndjson.open("w", encoding="utf-8") as fnd:
            writer = csv.writer(fcsv)
            writer.writerow(["file_path","source","title","authors","journal","pubdate","doi","url","pmid","arxiv_id","has_fulltext","pdf_path","html_path"])
            for p in papers:
                id_for_name = first(p.get("doi"), p.get("ids", {}).get("pmid"), p.get("ids", {}).get("arxiv"), p.get("title"), "paper")
                fname = sanitize_filename(id_for_name) + ".json"
                fpath = run_dir / fname
                with fpath.open("w", encoding="utf-8") as jf:
                    json.dump(p, jf, ensure_ascii=False, indent=2)
                saved_files.append(str(fpath.resolve()))
                writer.writerow([
                    str(fpath), p.get("source",""), p.get("title",""), p.get("authors",""),
                    p.get("journal",""), p.get("pubdate",""), p.get("doi",""), p.get("url",""),
                    p.get("ids",{}).get("pmid",""), p.get("ids",{}).get("arxiv",""),
                    p.get("has_fulltext",False), p.get("pdf_path",""), p.get("html_path","")
                ])
                fnd.write(json.dumps(p, ensure_ascii=False) + "\n")
        return saved_files, str(index_csv.resolve()), str(index_ndjson.resolve())

    def _save_batch_streaming(self, papers: List[Dict], run_dir: pathlib.Path, 
                              csv_writer, ndjson_file, saved_files_list: List[str]) -> int:
        """
        Save a batch of papers to disk and update index files (streaming mode).
        Returns the number of papers saved.
        """
        count = 0
        for p in papers:
            # Skip None entries that might come from failed enrichment
            if p is None:
                continue
            id_for_name = first(p.get("doi"), p.get("ids", {}).get("pmid"), p.get("ids", {}).get("arxiv"), p.get("title"), "paper")
            fname = sanitize_filename(id_for_name) + ".json"
            fpath = run_dir / fname
            
            try:
                # Save main JSON file
                with fpath.open("w", encoding="utf-8") as jf:
                    json.dump(p, jf, ensure_ascii=False, indent=2)
                
                saved_files_list.append(str(fpath.resolve()))
                
                csv_writer.writerow([
                    str(fpath), p.get("source",""), p.get("title",""), p.get("authors",""),
                    p.get("journal",""), p.get("pubdate",""), p.get("doi",""), p.get("url",""),
                    p.get("ids",{}).get("pmid",""), p.get("ids",{}).get("arxiv",""),
                    p.get("has_fulltext",False), p.get("pdf_path",""), p.get("html_path","")
                ])
                
                ndjson_file.write(json.dumps(p, ensure_ascii=False) + "\n")
                ndjson_file.flush()  # Ensure data is written immediately
                
                count += 1
            except Exception as e:
                log.error(f"Failed to save paper {fname}: {e}")
        
        return count

    # ---------------- Parallel workers ----------------
    def _resolve_url_to_pdf(self, url: str, max_redirects: int = 5) -> str:
        """
        Follow redirects and try to find actual PDF URL.
        Returns the final URL if it's a PDF, empty string otherwise.
        """
        cache_key = url.strip()
        if cache_key:
            cached = self._read_json_cache(self._resolution_cache_dir, cache_key)
            if cached and "resolved_url" in cached:
                return str(cached.get("resolved_url") or "")
        try:
            # Follow redirects with a one-shot HEAD request (no retry storm).
            response = requests.head(
                url,
                allow_redirects=True,
                timeout=(FULLTEXT_PDF_RESOLVE_CONNECT_TIMEOUT, FULLTEXT_PDF_RESOLVE_READ_TIMEOUT),
                headers={"User-Agent": "Enhanced-Journal-Search/2.0 (mailto: laozc@student.ubc.ca)"},
            )
            final_url = response.url
            content_type = response.headers.get('Content-Type', '').lower()
            
            # Check if final URL is a PDF
            if 'application/pdf' in content_type or final_url.lower().endswith('.pdf'):
                log.debug(f"[Resolve] {url[:60]} → PDF: {final_url[:60]}")
                if cache_key:
                    self._write_json_cache(self._resolution_cache_dir, cache_key, {"resolved_url": final_url, "saved_at": int(time.time())})
                return final_url
            
            # Check if final URL contains PDF patterns
            if '/pdf/' in final_url.lower() or 'download' in final_url.lower():
                # Try modifying URL to get PDF
                pdf_attempts = [
                    final_url + '.pdf',
                    final_url + '/pdf',
                    final_url.replace('/abstract/', '/pdf/'),
                    final_url.replace('/full', '/pdf'),
                ]
                
                for pdf_url in pdf_attempts:
                    try:
                        check = requests.head(
                            pdf_url,
                            allow_redirects=True,
                            timeout=(FULLTEXT_PDF_RESOLVE_CONNECT_TIMEOUT, FULLTEXT_PDF_RESOLVE_READ_TIMEOUT),
                            headers={"User-Agent": "Enhanced-Journal-Search/2.0 (mailto: laozc@student.ubc.ca)"},
                        )
                        if 'application/pdf' in check.headers.get('Content-Type', '').lower():
                            log.debug(f"[Resolve] Found PDF variant: {pdf_url[:60]}")
                            if cache_key:
                                self._write_json_cache(self._resolution_cache_dir, cache_key, {"resolved_url": pdf_url, "saved_at": int(time.time())})
                            return pdf_url
                    except Exception:
                        continue
            
            log.debug(f"[Resolve] {url[:60]} → Not a PDF (content-type: {content_type})")
            if cache_key:
                self._write_json_cache(self._resolution_cache_dir, cache_key, {"resolved_url": "", "saved_at": int(time.time())})
            return ""
            
        except Exception as e:
            log.debug(f"[Resolve] Failed to resolve {url[:60]}: {e}")
            if cache_key:
                self._write_json_cache(self._resolution_cache_dir, cache_key, {"resolved_url": "", "saved_at": int(time.time())})
            return ""

    def _odl_hybrid_server_available(self, hybrid_url: str) -> bool:
        check_url = (hybrid_url or "").strip() or "http://127.0.0.1:5002"
        try:
            # One-shot health probe: avoid retry storms when hybrid server is down.
            r = requests.get(
                f"{check_url.rstrip('/')}/health",
                timeout=(1.5, 2.5),
                headers={"User-Agent": "Enhanced-Journal-Search/2.0 (mailto: laozc@student.ubc.ca)"},
            )
            return 200 <= r.status_code < 300
        except Exception:
            return False

    def _normalize_odl_hybrid_timeout(self, timeout_raw: str) -> str:
        """
        OpenDataLoader CLI expects hybrid timeout in milliseconds.
        If the provided value looks like seconds (<=1000), convert to ms.
        """
        raw = str(timeout_raw or "").strip()
        if not raw:
            return raw
        try:
            val = int(raw)
        except Exception:
            return raw
        if 1 <= val <= 1000:
            normalized = str(val * 1000)
            log.warning(
                "[OpenDataLoader] hybrid_timeout=%s interpreted as seconds; using %s ms",
                raw,
                normalized,
            )
            return normalized
        return raw

    def _prepare_pdf_url_and_local_path(self, p: dict) -> Tuple[dict, Optional[pathlib.Path]]:
        if self._load_fulltext_cache(p):
            p["has_fulltext"] = True
            return p, None

        pdf_url = p.get("pdf_url") or ""
        if not pdf_url:
            return p, None

        if pdf_url.startswith("file://"):
            local_pdf_path = pathlib.Path(pdf_url.replace("file://", "", 1))
            if local_pdf_path.exists():
                return p, local_pdf_path
            return p, None
        if os.path.isabs(pdf_url):
            local_pdf_path = pathlib.Path(pdf_url)
            if local_pdf_path.exists():
                return p, local_pdf_path
            return p, None

        if pdf_url.startswith("https://doi.org/") or pdf_url.startswith("http://doi.org/"):
            resolved_url = self._resolve_url_to_pdf(pdf_url)
            if resolved_url:
                pdf_url = resolved_url
                p["pdf_url"] = resolved_url

        if "ncbi.nlm.nih.gov/pmc/articles/PMC" in pdf_url:
            match = re.search(r"(PMC\d+)", pdf_url)
            if match:
                pmcid = match.group(1)
                pdf_url = f"https://europepmc.org/articles/{pmcid}?pdf=render"
                p["pdf_url"] = pdf_url

        assets_dir = self._get_effective_assets_dir()
        if not assets_dir:
            import tempfile
            assets_dir = pathlib.Path(tempfile.gettempdir())
        fname = sanitize_filename(hashlib.md5(pdf_url.encode()).hexdigest()) + ".pdf"
        local_pdf_path = assets_dir / fname
        if not local_pdf_path.exists():
            if not self.download_to_path(pdf_url, local_pdf_path):
                return p, None
                
        if not self.is_valid_pdf(local_pdf_path):
            try:
                local_pdf_path.unlink() # Delete the fake file
            except Exception:
                pass
            return p, None

        return p, local_pdf_path

    def _extract_opendataloader_batch(self, papers: List[dict]) -> List[dict]:
        def _fallback_per_paper(paper_items: List[dict]) -> List[dict]:
            recovered: List[dict] = []
            for item in paper_items:
                p_item, local_pdf_path = self._prepare_pdf_url_and_local_path(item)
                if local_pdf_path is not None and local_pdf_path.exists():
                    p_item = self._extract_cached_or_local_pdf(p_item, local_pdf_path)
                recovered.append(p_item)
            return recovered

        try:
            import opendataloader_pdf  # type: ignore
        except Exception as e:
            log.warning(f"[OpenDataLoader] Package unavailable ({e}). Falling back to per-paper processing.")
            return _fallback_per_paper(papers)

        prepared: List[Tuple[dict, pathlib.Path]] = []
        cached_hits: List[dict] = []
        for p in papers:
            pp, local_pdf_path = self._prepare_pdf_url_and_local_path(p)
            if pp.get("has_fulltext") and pp.get("full_text"):
                cached_hits.append(pp)
                continue
            if local_pdf_path is not None:
                prepared.append((pp, local_pdf_path))

        if not prepared:
            return cached_hits if cached_hits else papers

        # Avoid expensive/noisy "batch then retry" when there is only one PDF.
        # This keeps recall unchanged and usually reduces latency for single-item chunks.
        if len(prepared) == 1:
            recovered = list(cached_hits)
            p_item, local_pdf_path = prepared[0]
            recovered.append(self._extract_cached_or_local_pdf(p_item, local_pdf_path))
            prepared_ids = {id(p_item)}
            prepared_ids.update(id(p) for p in cached_hits)
            for p in papers:
                if id(p) not in prepared_ids:
                    recovered.append(p)
            return recovered

        assets_dir = self._get_effective_assets_dir()
        if not assets_dir:
            import tempfile
            assets_dir = pathlib.Path(tempfile.gettempdir())

        base_convert_kwargs: Dict[str, Any] = {
            "format": "markdown",
            "quiet": True,
        }
        if self.odl_use_hybrid:
            hybrid_url = self.odl_hybrid_url or "http://127.0.0.1:5002"
            if self._odl_hybrid_server_available(hybrid_url):
                base_convert_kwargs["hybrid"] = self.odl_hybrid_model or "docling-fast"
                base_convert_kwargs["hybrid_url"] = hybrid_url
                if self.odl_hybrid_mode:
                    base_convert_kwargs["hybrid_mode"] = self.odl_hybrid_mode
                if self.odl_hybrid_timeout:
                    base_convert_kwargs["hybrid_timeout"] = self._normalize_odl_hybrid_timeout(self.odl_hybrid_timeout)
                base_convert_kwargs["hybrid_fallback"] = self.odl_hybrid_fallback
            else:
                log.warning("[OpenDataLoader] Hybrid server unavailable; using local mode for this batch.")

        updated: List[dict] = list(cached_hits)

        def _apply_markdown_or_fallback(batch_items: List[Tuple[dict, pathlib.Path]], out_dir: pathlib.Path) -> None:
            by_stem: Dict[str, pathlib.Path] = {}
            for md in out_dir.rglob("*.md"):
                by_stem[md.stem] = md
            for p_item, local_pdf_path in batch_items:
                md_path = by_stem.get(local_pdf_path.stem)
                text = ""
                if md_path and md_path.exists():
                    text = self.clean_extracted_text(md_path.read_text(encoding="utf-8", errors="ignore"))
                if text:
                    p_item.update({"full_text": text, "has_fulltext": True})
                    self._store_fulltext_cache(p_item, cache_origin="opendataloader_batch")
                else:
                    txt, tables, figures = self.pdf_to_text_tables_figures(local_pdf_path, local_pdf_path.parent)
                    fallback_text = self.clean_extracted_text(txt)
                    if fallback_text:
                        p_item.update({"full_text": fallback_text, "tables": tables, "figures": figures, "has_fulltext": True})
                        self._store_fulltext_cache(p_item, cache_origin="pdfminer_batch")
                updated.append(p_item)

        def _convert_subset(batch_items: List[Tuple[dict, pathlib.Path]]) -> None:
            if not batch_items:
                return
            out_dir = assets_dir / f"odl_batch_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
            out_dir.mkdir(parents=True, exist_ok=True)
            convert_kwargs: Dict[str, Any] = dict(base_convert_kwargs)
            convert_kwargs["input_path"] = [str(lp) for _, lp in batch_items]
            convert_kwargs["output_dir"] = str(out_dir)
            try:
                self._run_opendataloader_convert(convert_kwargs)
                _apply_markdown_or_fallback(batch_items, out_dir)
                return
            except Exception as e:
                if len(batch_items) == 1:
                    p_item, local_pdf_path = batch_items[0]
                    log.warning(f"[OpenDataLoader] Single-file conversion failed ({local_pdf_path.name}): {e}; using local fallback.")
                    updated.append(self._extract_cached_or_local_pdf(p_item, local_pdf_path))
                    return
                log.warning(f"[OpenDataLoader] Batch conversion failed for {len(batch_items)} files ({e}); splitting batch.")
                mid = len(batch_items) // 2
                _convert_subset(batch_items[:mid])
                _convert_subset(batch_items[mid:])

        _convert_subset(prepared)

        # include any papers that could not be prepared/downloaded
        prepared_ids = {id(p) for p, _ in prepared}
        prepared_ids.update(id(p) for p in cached_hits)
        for p in papers:
            if id(p) not in prepared_ids:
                updated.append(p)
        return updated
    
    def _pdf_worker_docling(self, p: dict) -> dict:
        pdf_url = p.get("pdf_url") or ""
        if not pdf_url:
            return p
        
        # Try to resolve DOI redirects to actual PDF URLs
        if pdf_url.startswith("https://doi.org/") or pdf_url.startswith("http://doi.org/"):
            log.debug(f"[Docling] DOI redirect detected, attempting to resolve: {pdf_url[:60]}")
            resolved_url = self._resolve_url_to_pdf(pdf_url)
            
            if resolved_url:
                pdf_url = resolved_url
                p["pdf_url"] = resolved_url  # Update with resolved URL
                log.info(f"[Docling] Resolved DOI to PDF: {resolved_url[:60]}")
            else:
                log.warning(f"[Docling SKIP] Could not resolve DOI to PDF: {pdf_url[:60]}")
                p["has_fulltext"] = False
                return p
        
        # Try to resolve landing pages to PDF URLs
        landing_page_patterns = [
            ("wiley.com/doi/", lambda u: u.replace('/doi/', '/doi/pdf/') if '/pdf/' not in u else u),
            ("onlinelibrary.wiley.com/doi/", lambda u: u.replace('/doi/', '/doi/pdf/') if '/pdf/' not in u else u),
            ("sciencedirect.com/science/article/pii/", lambda u: u.replace('/article/pii/', '/article/pii/') + '/pdf' if not u.endswith('/pdf') else u),
            ("springer.com/article/", lambda u: u.replace('/article/', '/content/pdf/') + '.pdf' if not u.endswith('.pdf') else u),
            ("nature.com/articles/", lambda u: u.replace('/articles/', '/articles/') + '.pdf' if not u.endswith('.pdf') else u),
        ]

        # Special handling for NCBI PMC URLs that serve interstitial pages
        # e.g. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12136755/pdf/?tool=EBI
        if "ncbi.nlm.nih.gov/pmc/articles/PMC" in pdf_url:
            try:
                # Extract PMCID
                match = re.search(r'(PMC\d+)', pdf_url)
                if match:
                    pmcid = match.group(1)
                    new_url = f"https://europepmc.org/articles/{pmcid}?pdf=render"
                    log.info(f"[Docling] Rewriting NCBI PMC URL to EuropePMC render: {pdf_url} -> {new_url}")
                    pdf_url = new_url
                    p["pdf_url"] = new_url
            except Exception as e:
                log.warning(f"[Docling] Failed to rewrite NCBI PMC URL: {e}")
        
        for pattern, transform in landing_page_patterns:
            if pattern in pdf_url.lower() and not pdf_url.lower().endswith('.pdf'):
                attempted_pdf_url = transform(pdf_url)
                resolved_url = self._resolve_url_to_pdf(attempted_pdf_url)
                
                if resolved_url:
                    pdf_url = resolved_url
                    p["pdf_url"] = resolved_url
                    log.info(f"[Docling] Resolved landing page to PDF: {resolved_url[:60]}")
                    break
                else:
                    log.debug(f"[Docling] Could not resolve landing page: {pdf_url[:60]}")
        
        # Now try Docling with the (possibly resolved) URL
        success = False
        try:
            # Check file size before processing if possible (requires HEAD request or download)
            # Since docling_url_to_text handles download, we can add a check there or rely on its robustness.
            # For now, we rely on the serial execution fix to prevent crashes.
            text, tables, figures = self.docling_url_to_text(pdf_url)
            if text:
                p.update({"full_text": text, "tables": tables, "figures": figures, "has_fulltext": True})
                log.info(f"[Docling OK] {p.get('source','')}: {p.get('title','')[:60]}")
                success = True
            else:
                log.warning(f"[Docling EMPTY] {p.get('source','')}: {p.get('title','')[:60]}")
        except Exception as e:
            log.warning(f"[Docling FAIL] {pdf_url[:80]}: {str(e)[:100]}")

        # Fallback: If failed and we have a PMCID, try the Europe PMC PDF
        if not success:
            ids = p.get("ids", {}) or {}
            pmcid = ids.get("pmcid")
            # Avoid infinite loop if the original URL was already the fallback
            if pmcid and "europepmc.org" not in pdf_url:
                fallback_url = f"https://europepmc.org/articles/{pmcid}?pdf=render"
                log.info(f"[Docling] Retrying with fallback PMC URL: {fallback_url}")
                try:
                    text, tables, figures = self.docling_url_to_text(fallback_url)
                    if text:
                        p.update({"full_text": text, "tables": tables, "figures": figures, "has_fulltext": True, "pdf_url": fallback_url})
                        log.info(f"[Docling FALLBACK OK] {p.get('title','')[:60]}")
                        success = True
                except Exception as e:
                    log.warning(f"[Docling FALLBACK FAIL] {fallback_url}: {e}")

        if not success:
            # Try Unpaywall if not already done
            pass # (Existing Unpaywall logic...)
        return p

    def _batch_resolve_pmcids(self, papers: List[Dict]) -> None:
        """Batch resolves PMIDs to PMCIDs using the highly stable PMC ID Converter API."""
        pmid_to_paper = {}
        for p in papers:
            if not p or p.get("has_fulltext"): 
                continue
            
            ids = p.get("ids", {}) or {}
            pmid = ids.get("pmid")
            pmcid = ids.get("pmcid")
            
            if pmid and not pmcid:
                cached = self._read_json_cache(self._pmcid_cache_dir, str(pmid))
                if cached and cached.get("pmcid"):
                    p["ids"]["pmcid"] = str(cached.get("pmcid"))
                    if cached.get("doi") and not p["ids"].get("doi"):
                        p["ids"]["doi"] = str(cached.get("doi"))
                        p["doi"] = str(cached.get("doi"))
                    continue
                pmid_to_paper[str(pmid)] = p

        pmids_to_resolve = list(pmid_to_paper.keys())
        if not pmids_to_resolve:
            return

        # PMC ID Converter API allows up to 200 IDs per request. Let's use 100 to be safe.
        chunk_size = 100
        
        for i in range(0, len(pmids_to_resolve), chunk_size):
            chunk = pmids_to_resolve[i:i + chunk_size]
            id_string = ",".join(chunk)
            log.info(f"Batch resolving {len(chunk)} PMIDs to PMCIDs via ID Converter API (chunk {i//chunk_size + 1})...")
            
            params = {
                "ids": id_string,
                "format": "json",
                "tool": "Enhanced-Journal-Search",
                "email": self._entrez_email
            }
            
            url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
            
            try:
                # Apply global rate limit lock across all threads
                with _ENTREZ_LOCK:
                    global _LAST_ENTREZ_CALL
                    now = time.time()
                    elapsed = now - _LAST_ENTREZ_CALL
                    if elapsed < ENTREZ_RATE_LIMIT:
                        time.sleep(ENTREZ_RATE_LIMIT - elapsed)
                    _LAST_ENTREZ_CALL = time.time()
                    
                    r = self._http.get(url, params=params, timeout=30)
                    r.raise_for_status()
                    data = r.json()
                
                # Parse the JSON response from the ID Converter
                records = data.get("records", [])
                for rec in records:
                    orig_pmid = str(rec.get("pmid", ""))
                    pmcid = rec.get("pmcid", "")
                    
                    # Map back to the original paper dictionary
                    if orig_pmid and pmcid and orig_pmid in pmid_to_paper:
                        paper = pmid_to_paper[orig_pmid]
                        if "ids" not in paper:
                            paper["ids"] = {}
                        paper["ids"]["pmcid"] = pmcid
                        
                        # Bonus: The API also returns DOIs. Grab it if we don't have it!
                        if not paper["ids"].get("doi") and rec.get("doi"):
                            paper["ids"]["doi"] = rec.get("doi")
                            paper["doi"] = rec.get("doi")
                        self._write_json_cache(
                            self._pmcid_cache_dir,
                            orig_pmid,
                            {
                                "pmcid": pmcid,
                                "doi": rec.get("doi", ""),
                                "saved_at": int(time.time()),
                            },
                        )
                            
            except Exception as e:
                log.warning(f"Batch PMC ID conversion chunk failed: {e}")

    def _phase1_enrich_one(self, p: dict) -> dict:
        """Attempt JATS and Unpaywall for a single paper (no downloads)."""
        if p.get("has_fulltext"):
            return p
        if self._load_fulltext_cache(p):
            p["has_fulltext"] = True
            return p
        try:
            source = p.get("source", "")
            ids = p.get("ids", {}) or {}
            doi = p.get("doi") or ids.get("doi") or ""
            xml_url = p.get("xml_url") or ""
            pdf_url = p.get("pdf_url") or ""
            html_url = p.get("html_url") if "html_url" in p else ""
            full_text = ""
            sections = []

            # 0) Hydrate previously marked offline hits lazily
            offline_doc_id = p.get("offline_doc_id")
            if source in ("OfflineDB", "offline_db") and offline_doc_id:
                local_file = None
                local_txt_path = str(p.get("local_txt_path") or "").strip()
                local_pdf_path = str(p.get("local_pdf_path") or "").strip()
                if local_txt_path:
                    txt_candidate = pathlib.Path(local_txt_path)
                    if not txt_candidate.exists() and self.offline_doc_dir:
                        txt_candidate = pathlib.Path(self.offline_doc_dir) / local_txt_path
                    if txt_candidate.exists():
                        local_file = txt_candidate
                if local_file is None and self.offline_doc_dir:
                    candidate = pathlib.Path(self.offline_doc_dir) / str(offline_doc_id)
                    if candidate.exists():
                        local_file = candidate
                if local_file is not None:
                    try:
                        full_text = local_file.read_text(encoding="utf-8")
                    except Exception as e:
                        log.warning(f"Failed to read local offline file {local_file}: {e}")
                if not full_text and local_pdf_path:
                    pdf_candidate = pathlib.Path(local_pdf_path)
                    if not pdf_candidate.exists() and self.offline_doc_dir:
                        pdf_candidate = pathlib.Path(self.offline_doc_dir) / local_pdf_path
                    if pdf_candidate.exists():
                        try:
                            full_text = pdf_extract_text(str(pdf_candidate))
                        except Exception as e:
                            log.warning(f"Failed to extract text from local offline PDF {pdf_candidate}: {e}")
                if not full_text:
                    full_text = str(p.get("offline_chunk_text") or "")
                    if full_text:
                        p["offline_chunk_only"] = True
                if full_text:
                    p["full_text"] = full_text
                    p["has_fulltext"] = True
                    log.info(f"[Offline Hit] Hydrated text for '{p.get('title','')[:30]}...'")
                    return p

            # 1) Europe PMC JATS fullTextXML
            if self.include_online_search and source.startswith("EuropePMC:") and ids.get("eupmc_id"):
                src_tag = source.split(":",1)[1]
                full_text, sections, xml_path = self.eupmc_fulltext_jats(src_tag, ids["eupmc_id"])
                if full_text:
                    p.update({"full_text": full_text, "sections": sections, "html_path": xml_path or "", "has_fulltext": True})
                    self._store_fulltext_cache(p, cache_origin="eupmc_jats")
                    log.info(f"[EUPMC JATS OK] {p.get('title','')[:60]}")
                    return p

            # 2) PubMed Central via pre-resolved PMCID
            pmcid = ids.get("pmcid") or ""
            if self.include_online_search and pmcid and not full_text:
                try:
                    # Strip "PMC" prefix for the Entrez API
                    pmcid_numeric = "".join(filter(str.isdigit, pmcid))
                    if pmcid_numeric:
                        raw_xml = self._entrez_get_bytes(
                            Entrez.efetch, f"during efetch(pmc) for {pmcid}",
                            db="pmc", id=pmcid_numeric, retmode="xml"
                        )
                        root = ET.fromstring(raw_xml)
                        sections = jats_nodes_to_sections(root)
                        full_text = sections_to_markdown(sections)
                        
                        if full_text:
                            p.update({"full_text": full_text, "sections": sections, "has_fulltext": True})
                            self._store_fulltext_cache(p, cache_origin="pmc_efetch")
                            log.info(f"[PMC OK] {source}: {p.get('title','')[:60]}")
                            return p
                except Exception as e:
                    log.debug(f"Direct efetch PMC extraction failed for {pmcid}: {e}")

                # Fallback using a different URL structure if still no text
                if not full_text:
                    try:
                        alt_xml_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
                        full_text, sections, _ = self.get_jats_fulltext_from_url(alt_xml_url)
                        if full_text:
                            p.update({"full_text": full_text, "sections": sections, "has_fulltext": True})
                            self._store_fulltext_cache(p, cache_origin="pmc_html")
                            log.info(f"SUCCESS: Alternative URL fetch for PMCID {pmcid} succeeded.")
                            return p
                    except Exception as e:
                        log.debug(f"Alternative URL fetch for {pmcid} failed: {e}")

            # 3) Explicit XML URL (e.g., medRxiv)
            if xml_url and not full_text:
                ft, sections, maybe_xml_path = self.get_jats_fulltext_from_url(xml_url)
                if ft:
                    p.update({"full_text": ft, "sections": sections, "html_path": maybe_xml_path or "", "has_fulltext": True})
                    self._store_fulltext_cache(p, cache_origin="xml_url")
                    log.info(f"[JATS OK] {source}: {p.get('title','')[:60]}")
                    return p

            # 4) Unpaywall - Enhanced to get direct PDF URLs
            if doi and not pdf_url and not full_text:
                up_pdf, up_landing = self.unpaywall_lookup(doi, email=self._entrez_email)
                if up_pdf:
                    if up_pdf.lower().endswith('.pdf') or '/pdf/' in up_pdf.lower():
                        p["pdf_url"] = up_pdf
                        log.debug(f"[Unpaywall] Found PDF: {up_pdf[:80]}")
                    else:
                        if not html_url:
                            p["html_url"] = up_pdf
                        log.debug(f"[Unpaywall] Found landing page (not PDF): {up_pdf[:80]}")
                elif up_landing and not html_url:
                    p["html_url"] = up_landing

            # 5) Construct PMC PDF URL if we have PMCID but no PDF URL
            if pmcid and not pdf_url and not full_text:
                candidate_pdf = f"https://europepmc.org/articles/{pmcid}?pdf=render"
                p["pdf_url"] = candidate_pdf
                log.debug(f"[PMC] Constructed PDF URL (via EuropePMC): {candidate_pdf}")

        except Exception as e:
            log.debug(f"Phase-1 enrich failed for {p.get('title','')[:60]}: {e}")
        return p

    # ---------------- Orchestrator ----------------
    def _run(
        self,
        query: Optional[str | List[str]] = None,
        identity_terms: Optional[List[str]] = None,
        context_terms: Optional[List[str]] = None,
        max_results: int = FULLTEXT_SEARCH_DEFAULT_MAX_RESULTS,
        max_results_pubmed: Optional[int] = None,
        max_results_eupmc: Optional[int] = None,
        max_results_s2: Optional[int] = None,
        max_results_arxiv: Optional[int] = None,
        max_results_medrxiv: Optional[int] = None,
        max_results_chemrxiv: Optional[int] = None,
        min_date: Optional[str] = None,
        max_date: Optional[str] = None,
        processing_chunk_size: int = 50,
        offline_index_path: Optional[str] = None,
        offline_sqlite_path: Optional[str] = None,
        offline_doc_dir: Optional[str] = None,
        **kwargs
    ) -> str:
        # allow per-call flags
        for flag in [
            "include_online_search", "include_offline_search", # ADDED FOR DYNAMIC CONTROL
            "include_pubmed","include_preprints","include_s2","include_arxiv","include_medrxiv",
            "include_chemrxiv","include_eupmc","use_pubmed_free_fulltext_bias",
            "max_parallel_downloads","max_search_workers","max_phase1_workers","max_parallel_docling",
            "offline_doc_dir", "offline_sqlite_path", "enable_offline_vector_search", "offline_vector_model", "pdf_text_extractor",
            "odl_use_hybrid", "odl_hybrid_model", "odl_hybrid_mode", "odl_hybrid_url",
            "odl_hybrid_timeout", "odl_hybrid_fallback"
        ]:
            if flag in kwargs:
                setattr(self, flag, kwargs.get(flag, getattr(self, flag)))

        # Explicitly handle offline_index_path since it is a named argument
        if offline_index_path:
            self.offline_index_path = offline_index_path
        elif "offline_index_path" in kwargs:
            self.offline_index_path = kwargs["offline_index_path"]
        if offline_sqlite_path:
            self.offline_sqlite_path = offline_sqlite_path
        if "offline_sqlite_path" in kwargs and kwargs["offline_sqlite_path"]:
            self.offline_sqlite_path = kwargs["offline_sqlite_path"]

        # Store date range parameters
        date_min = min_date or self.min_date
        date_max = max_date or self.max_date
        
        offline_docs_path = pathlib.Path(offline_doc_dir or self.offline_doc_dir or "/data/chen/pubmed_corpus/pmc_extracted_text")
        

        if self.include_offline_search and self.offline_sqlite_path and self._offline_sqlite_conn is None:
            try:
                if os.path.exists(self.offline_sqlite_path):
                    self._offline_sqlite_conn = self._init_offline_doc_db(self.offline_sqlite_path)
                    log.info(f"Connected to offline SQLite metadata DB at {self.offline_sqlite_path}")
                else:
                    log.warning(f"Offline SQLite DB path not found: {self.offline_sqlite_path}")
            except Exception as e:
                log.error(f"Failed to connect to offline SQLite DB: {e}")

        # Determine k for each source, falling back to the global max_results
        k_global = max_results # The global default
        k_pubmed = max_results_pubmed if max_results_pubmed is not None else k_global
        k_eupmc = max_results_eupmc if max_results_eupmc is not None else k_global
        k_s2 = max_results_s2 if max_results_s2 is not None else k_global
        k_arxiv = max_results_arxiv if max_results_arxiv is not None else k_global
        k_medrxiv = max_results_medrxiv if max_results_medrxiv is not None else k_global
        k_chemrxiv = max_results_chemrxiv if max_results_chemrxiv is not None else k_global

        queries = _generate_mechanical_query_batch(
            query=query,
            identity_terms=identity_terms,
            context_terms=context_terms,
        )
        
        # Validation
        if not queries:
            return "Error: No query provided."
            
        log.info(f"Queries: {queries}")
        # ---- Resolve session dir
        session_dir = _SESSION_DIR_CVAR.get()
        if session_dir:
            run_dir = pathlib.Path(session_dir).resolve()
            log.info(f"Using session directory: {run_dir}")
        else:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            configured = getattr(self, "results_base_dir", None)
            base_dir = pathlib.Path(configured or pathlib.Path(__file__).resolve().parent / "searching_results").resolve()
            run_dir = (base_dir / f"run_{ts}").resolve()
            log.warning("search_session_dir not in config/callback! Using tool default directory.")
        run_dir.mkdir(parents=True, exist_ok=True)

        # ---------------- Parallel source searches ----------------
        all_results: List[Dict] = []
        source_counts: Dict[str,int] = {}
        
        futures_map = {} # future -> (source_name, query)

        with ThreadPoolExecutor(max_workers=self.max_search_workers) as ex:
            # 1. Schedule ONLINE tasks
            if self.include_online_search:
                for q in queries:
                    # PubMed
                    if self.include_pubmed:
                        futures_map[ex.submit(self.search_pubmed_pmc, q, k_pubmed, date_min, date_max)] = ("PubMed", q)
                    # EuropePMC
                    if self.include_eupmc:
                         futures_map[ex.submit(self.search_eupmc, q, k_eupmc, date_min, date_max)] = ("EuropePMC", q)
                    # SemanticScholar
                    if self.include_s2:
                         futures_map[ex.submit(self.search_semantic_scholar, q, k_s2, date_min, date_max)] = ("SemanticScholar", q)
                    # Preprints
                    if self.include_preprints:
                        if self.include_arxiv:
                             futures_map[ex.submit(self.search_arxiv, q, k_arxiv)] = ("arXiv", q)
                        if self.include_medrxiv:
                             futures_map[ex.submit(self.search_medrxiv, q, k_medrxiv)] = ("medRxiv", q)
                        if self.include_chemrxiv:
                             futures_map[ex.submit(self.search_chemrxiv_via_figshare, q, k_chemrxiv)] = ("ChemRxiv", q)
            
            # 2. Schedule OFFLINE tasks
            if self.include_offline_search and (self._offline_sqlite_conn or self._offline_sqlite_conns):
                for q in queries:
                    # Note: We use global k for offline_db usually, or maybe double it since it's cleaner
                    futures_map[ex.submit(self._search_offline_doc_db, q, k_global)] = ("OfflineDB", q)
            
            # 3. Collect Results
            for fut in as_completed(futures_map):
                src, q_used = futures_map[fut]
                try:
                    res = fut.result()
                    if res:
                        for rank_idx, item in enumerate(res, start=1):
                            if isinstance(item, dict):
                                item["_retrieval_source"] = src
                                item["_retrieval_query"] = q_used
                                item["_retrieval_rank"] = rank_idx
                        all_results.extend(res)
                        source_counts[src] = source_counts.get(src, 0) + len(res)
                except Exception as e:
                    log.error(f"Search task failed for {src} (q='{q_used}'): {e}")
        total_results = len(all_results)
        papers = _apply_rrf_fusion(all_results)
        all_results.clear()
        log.info(f"Found {total_results} results total, {len(papers)} unique. Enriching...")
        log.info(f"Raw source counts before deduplication: {source_counts}")
        if papers:
            log.info(
                "RRF fusion complete. Top fused hits: "
                + ", ".join(
                    f"{(p.get('title') or '')[:50]} (rrf={p.get('_rrf_score', 0.0):.4f}, hits={p.get('_rrf_hits', 0)})"
                    for p in papers[:5]
                )
            )

        # Relative-score filtering on fused retrieval support.
        # This trims weak-tail noise before expensive enrichment while preserving
        # high-consensus candidates.
        if papers and FULLTEXT_SEARCH_RRF_FILTER_ENABLE:
            pre_count = len(papers)
            max_rrf = float(papers[0].get("_rrf_score", 0.0) or 0.0)
            cutoff = max_rrf * max(0.0, FULLTEXT_SEARCH_RRF_RELATIVE_THRESHOLD)
            filtered = [
                p for p in papers
                if float(p.get("_rrf_score", 0.0) or 0.0) >= cutoff
                or int(p.get("_rrf_hits", 0) or 0) >= FULLTEXT_SEARCH_RRF_MIN_HITS
            ]
            if len(filtered) < FULLTEXT_SEARCH_RRF_MIN_KEEP:
                filtered = papers[: min(FULLTEXT_SEARCH_RRF_MIN_KEEP, pre_count)]
            if FULLTEXT_SEARCH_RRF_MAX_KEEP > 0 and len(filtered) > FULLTEXT_SEARCH_RRF_MAX_KEEP:
                filtered = filtered[:FULLTEXT_SEARCH_RRF_MAX_KEEP]
            papers = filtered
            log.info(
                "RRF filter kept %s/%s papers (max_rrf=%.4f, cutoff=%.4f, min_hits=%s, min_keep=%s, max_keep=%s).",
                len(papers),
                pre_count,
                max_rrf,
                cutoff,
                FULLTEXT_SEARCH_RRF_MIN_HITS,
                FULLTEXT_SEARCH_RRF_MIN_KEEP,
                FULLTEXT_SEARCH_RRF_MAX_KEEP,
            )

        # Keep paper-level retrieval broad. Defer expensive precision to snippet-level
        # reranking in fulltext_query, which operates closer to the final evidence spans.

        # Default behavior: keep all retrieval-supported papers and defer precision to
        # snippet-level querying/reranking. If a limit is needed later, it should be
        # introduced explicitly as a separate config rather than tied to max_results.
        # --- END CHANGE ---

            def _norm_title_simple(t: str) -> str:
                return re.sub(r"\s+", " ", str(t).lower().strip())

            def _title_tokens(t: str) -> set[str]:
                stop = {
                    "the", "and", "for", "with", "from", "into", "during", "after", "over",
                    "under", "in", "on", "of", "to", "a", "an", "by", "as", "or", "at",
                    "via", "using", "new", "study", "review", "analysis", "water",
                }
                toks = re.findall(r"[a-z0-9]+", str(t).lower())
                return {tok for tok in toks if len(tok) >= 5 and tok not in stop}

            def _title_overlap_count(title: str, text: str) -> int:
                if not title or not text:
                    return 0
                tt = _title_tokens(title)
                if not tt:
                    return 0
                low_text = str(text).lower()
                return sum(1 for tok in tt if tok in low_text)

            def _should_replace_with_offline(existing_text: str, offline_text: str, title: str) -> bool:
                # If no current text, any non-empty offline text is useful.
                if not str(existing_text or "").strip():
                    return bool(str(offline_text or "").strip())

                off = str(offline_text or "").strip()
                cur = str(existing_text or "").strip()
                if not off:
                    return False

                off_len = len(off)
                cur_len = len(cur)
                off_ov = _title_overlap_count(title, off)
                cur_ov = _title_overlap_count(title, cur)

                # Prefer offline text only when it is clearly better aligned or richer.
                if off_ov > cur_ov:
                    return True
                if off_ov == cur_ov and off_len >= int(cur_len * 1.2):
                    return True
                return False

            offline_candidates = [p for p in papers if p and p.get("source") in ("OfflineDB", "offline_db")]
            offline_by_doi: Dict[str, Dict] = {}
            offline_by_pmid: Dict[str, Dict] = {}
            offline_by_title: Dict[str, Dict] = {}

            for op in offline_candidates:
                doi_val = str(op.get("doi") or (op.get("ids", {}) or {}).get("doi") or "").strip().lower()
                if doi_val and doi_val not in offline_by_doi:
                    offline_by_doi[doi_val] = op
                pmid_val = str((op.get("ids", {}) or {}).get("pmid") or "").strip()
                if pmid_val and pmid_val not in offline_by_pmid:
                    offline_by_pmid[pmid_val] = op
                title_key = _norm_title_simple(op.get("title", ""))
                if title_key and title_key not in offline_by_title:
                    offline_by_title[title_key] = op

            matched_count = 0
            for p in papers:
                if not p:
                    continue
                if p.get("source") in ("OfflineDB", "offline_db"):
                    continue

                match = None
                doi_val = str(p.get("doi") or (p.get("ids", {}) or {}).get("doi") or "").strip().lower()
                pmid_val = str((p.get("ids", {}) or {}).get("pmid") or "").strip()
                title_val = str(p.get("title", "") or "")

                if doi_val and doi_val in offline_by_doi:
                    match = offline_by_doi[doi_val]
                elif pmid_val and pmid_val in offline_by_pmid:
                    match = offline_by_pmid[pmid_val]
                else:
                    title_key = _norm_title_simple(title_val)
                    if title_key and title_key in offline_by_title:
                        match = offline_by_title[title_key]
                    elif title_val:
                        # Small fallback over already-retrieved offline titles only.
                        for offline_title_key, offline_item in offline_by_title.items():
                            if title_close(title_val, offline_item.get("title", "")):
                                match = offline_item
                                break

                if not match:
                    continue

                offline_text = match.get("full_text") or ""
                existing_text = p.get("full_text") or ""
                if offline_text and _should_replace_with_offline(existing_text, offline_text, title_val):
                    p["source"] = "OfflineDB"
                    if match.get("offline_doc_id"):
                        p["offline_doc_id"] = match.get("offline_doc_id")
                        p["offline_chunk_text"] = match.get("offline_chunk_text") or offline_text
                        if match.get("local_txt_path"):
                            p["local_txt_path"] = match.get("local_txt_path")
                        if match.get("local_pdf_path"):
                            p["local_pdf_path"] = match.get("local_pdf_path")
                        # Force phase-1 local hydration so we use full document context,
                        # not only the offline chunk payload.
                        p.pop("full_text", None)
                        p["has_fulltext"] = False
                    else:
                        p["full_text"] = offline_text
                        p["has_fulltext"] = True
                if match.get("doi") and not p.get("doi"):
                    p["doi"] = match.get("doi")
                if isinstance(match.get("ids"), dict):
                    ids = dict(p.get("ids", {}) or {})
                    for k, v in match["ids"].items():
                        if v and not ids.get(k):
                            ids[k] = v
                    p["ids"] = ids
                matched_count += 1

            log.info(f"Offline metadata matching complete. Matched {matched_count} papers using retrieved offline candidates.")

        # -------- Phase 1 & 2: JATS + Unpaywall + PDF processing, STREAMING to disk in chunks --------
        # Reuse previously saved hydrated records in the same run_dir to avoid re-downloading/re-parsing
        # the same papers across iterative calls.
        hydrated_cache: Dict[str, Dict[str, Any]] = {}
        try:
            for fp in run_dir.glob("*.json"):
                if fp.name in {"index.ndjson"}:
                    continue
                try:
                    rec = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                key = _paper_identity_key(rec)
                if not key:
                    continue
                hydrated_cache[key] = rec
        except Exception as e:
            log.debug(f"Hydration cache load failed in {run_dir}: {e}")

        if hydrated_cache:
            reused = 0
            reused_full = 0
            for idx, p in enumerate(papers):
                key = _paper_identity_key(p)
                cached = hydrated_cache.get(key)
                if not cached:
                    continue
                papers[idx] = _merge_paper_records(p, cached)
                reused += 1
                if papers[idx].get("has_fulltext"):
                    reused_full += 1
            log.info(f"Hydration cache reuse: merged {reused} papers ({reused_full} already fulltext).")

        index_csv = run_dir / "index.csv"
        index_ndjson = run_dir / "index.ndjson"
        all_saved_files = []
        
        with index_csv.open("w", newline="", encoding="utf-8") as fcsv, \
             index_ndjson.open("w", encoding="utf-8") as fnd:
            
            writer = csv.writer(fcsv)
            writer.writerow(["file_path","source","title","authors","journal","pubdate","doi","url","pmid","arxiv_id","has_fulltext","pdf_path","html_path"])

            # Process papers in chunks to manage memory
            for i in range(0, len(papers), processing_chunk_size):
                chunk = papers[i:i + processing_chunk_size]
                log.info(f"Processing chunk {i//processing_chunk_size + 1}/{(len(papers) + processing_chunk_size - 1)//processing_chunk_size} ({len(chunk)} papers)")

                # --- NEW BATCH RESOLUTION STEP ---
                if self.include_online_search:
                    self._batch_resolve_pmcids(chunk)
                # ---------------------------------

                # --- Phase 1: JATS + Unpaywall ---
                enriched_chunk_phase1 = []
                with ThreadPoolExecutor(max_workers=self.max_phase1_workers) as ex:
                    futures = []
                    for p in chunk:
                        ctx = copy_context()
                        futures.append(ex.submit(ctx.run, self._phase1_enrich_one, p))
                    
                    for fut in as_completed(futures):
                        try:
                            enriched_chunk_phase1.append(fut.result())
                        except Exception as e:
                            log.error(f"Phase-1 enrichment future failed: {e}")

                # --- Phase 2: PDF processing ---
                papers_for_pdf = [p for p in enriched_chunk_phase1 if p.get("pdf_url") and not p.get("has_fulltext")]
                
                final_enriched_chunk = []
                if papers_for_pdf:
                    processed_non_pdf = [p for p in enriched_chunk_phase1 if not (p.get("pdf_url") and not p.get("has_fulltext"))]
                    final_enriched_chunk.extend(processed_non_pdf)

                    if self.pdf_text_extractor == "opendataloader":
                        final_enriched_chunk.extend(self._extract_opendataloader_batch(papers_for_pdf))
                    else:
                        with ThreadPoolExecutor(max_workers=self.max_parallel_docling) as ex:
                            pdf_futures = {}
                            for p in papers_for_pdf:
                                ctx = copy_context()
                                pdf_futures[ex.submit(ctx.run, self._pdf_worker_docling, p)] = p

                            for fut in as_completed(pdf_futures):
                                try:
                                    final_enriched_chunk.append(fut.result())
                                except Exception as e:
                                    original_paper = pdf_futures[fut]
                                    log.error(f"PDF worker future failed for {original_paper.get('title', 'N/A')[:50]}: {e}")
                                    final_enriched_chunk.append(original_paper) # append original on failure
                else:
                    final_enriched_chunk = enriched_chunk_phase1

                # --- ABSTRACT FALLBACK: For papers without full_text, use abstract ---
                for p in final_enriched_chunk:
                    if not p:
                        continue
                    if not p.get("has_fulltext") and not p.get("full_text"):
                        abstract = p.get("abstract", "")
                        if abstract:
                            p["full_text"] = abstract  # Use abstract as content
                            p["has_fulltext"] = False  # Explicitly mark as abstract-only
                            p["abstract_only"] = True  # New flag for clarity
                            log.info(f"[Abstract Fallback] Using abstract for: {p.get('title', '')[:50]}")

                # Save the fully processed chunk
                saved_count = self._save_batch_streaming(final_enriched_chunk, run_dir, writer, fnd, all_saved_files)
                log.info(f"Saved {saved_count} papers from this chunk.")
                fcsv.flush() # ensure the csv is written to disk per chunk
                fnd.flush()

                chunk_end = min(i + processing_chunk_size, len(papers))
                for idx in range(i, chunk_end):
                    papers[idx] = None

                del chunk, enriched_chunk_phase1, papers_for_pdf, final_enriched_chunk
                gc.collect()

        log.info(f"Enrichment complete. Total papers saved: {len(all_saved_files)}")
        papers = None

        return json.dumps(
            {
                "error": False,
                "generated_queries": queries,
                "total_papers_found": len(all_saved_files),
                "run_path": str(run_dir),
            },
            ensure_ascii=False,
        )

    # --- Helper to fetch arbitrary JATS XML URL (used by medRxiv, etc.)
    def get_jats_fulltext_from_url(self, xml_url: str) -> Tuple[str, List[Dict[str, str]], Optional[str]]:
        if not xml_url:
            return "", [], None
        try:
            r = self._http.get(xml_url, timeout=60)
            if r.status_code == 404:
                log.debug(f"JATS XML not found (404): {xml_url}")
                return "", [], None
            r.raise_for_status()
            xml_path = None
            assets_dir = self._get_effective_assets_dir()
            if assets_dir:
                fname_part = xml_url.split('/')[-1].replace('.xml', '').replace('.source', '')
                xml_name = sanitize_filename(fname_part) + ".xml"
                xml_fpath = assets_dir / xml_name
                xml_fpath.write_bytes(r.content)
                xml_path = str(xml_fpath)

            content_type = (r.headers.get("content-type") or "").lower()
            if "html" in content_type or xml_url.rstrip("/").startswith("https://www.ncbi.nlm.nih.gov/pmc/articles/"):
                html = r.text
                sections = pmc_html_to_sections(html)
                full_text = sections_to_markdown(sections)
                return full_text, sections, xml_path

            root = ET.fromstring(r.content)
            sections = jats_nodes_to_sections(root)
            full_text = sections_to_markdown(sections)
            return full_text, sections, xml_path
        except Exception as e:
            log.debug(f"JATS XML fetch/parse failed for {xml_url}: {e}")
            return "", [], None
