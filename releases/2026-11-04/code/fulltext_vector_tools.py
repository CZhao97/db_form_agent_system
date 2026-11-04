from __future__ import annotations
import os, re, json, pathlib, logging, threading
from typing import List, Dict, Optional, Any, Type, Set
from collections.abc import Mapping, Iterable
from contextvars import ContextVar

from pydantic import BaseModel, Field
from langchain.tools import BaseTool

from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.runnables import RunnableConfig

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None
try:
    import torch
except ImportError:
    torch = None
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.runnables import RunnableConfig

log = logging.getLogger("fulltext_vector_tools")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

FULLTEXT_QUERY_DEFAULT_K = int(os.environ.get("FULLTEXT_QUERY_DEFAULT_K", "40"))
FULLTEXT_QUERY_MIN_FETCH = int(os.environ.get("FULLTEXT_QUERY_MIN_FETCH", "120"))
FULLTEXT_QUERY_FETCH_MULTIPLIER = int(os.environ.get("FULLTEXT_QUERY_FETCH_MULTIPLIER", "4"))
FULLTEXT_QUERY_MAX_QUERIES = int(os.environ.get("FULLTEXT_QUERY_MAX_QUERIES", "36"))
FULLTEXT_INDEX_DEFAULT_CHUNK_SIZE = int(os.environ.get("FULLTEXT_INDEX_DEFAULT_CHUNK_SIZE", "1200"))
FULLTEXT_INDEX_DEFAULT_CHUNK_OVERLAP = int(os.environ.get("FULLTEXT_INDEX_DEFAULT_CHUNK_OVERLAP", "180"))
FULLTEXT_INDEX_MIN_SUBSTANTIVE_CHARS = int(os.environ.get("FULLTEXT_INDEX_MIN_SUBSTANTIVE_CHARS", "160"))
FULLTEXT_RERANK_MODEL = os.environ.get("FULLTEXT_RERANK_MODEL", "BAAI/bge-reranker-v2-m3").strip() or "BAAI/bge-reranker-v2-m3"
FULLTEXT_RERANK_FALLBACK_MODEL = os.environ.get("FULLTEXT_RERANK_FALLBACK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2").strip() or "cross-encoder/ms-marco-MiniLM-L-6-v2"
FULLTEXT_RERANK_DEVICE = os.environ.get("FULLTEXT_RERANK_DEVICE", "").strip().lower()


def _infer_section_type(section_title: str, abstract_only: bool = False, offline_chunk_only: bool = False) -> str:
    if offline_chunk_only:
        return "offline_chunk"
    if abstract_only:
        return "abstract"
    title = (section_title or "").strip().lower()
    if not title:
        return "full_text"
    if "method" in title or "experimental" in title or "materials" in title:
        return "methods"
    if "result" in title:
        return "results"
    if "discussion" in title:
        return "discussion"
    if "conclusion" in title:
        return "conclusion"
    if "supplement" in title or "supporting" in title:
        return "supplement"
    if "table" in title or "figure" in title:
        return "caption"
    if "abstract" in title:
        return "abstract"
    if "introduction" in title or "background" in title:
        return "introduction"
    return "other"


def _normalize_run_path_input(run_path: str, results_base_dir: Optional[str] = None) -> pathlib.Path:
    p = pathlib.Path(run_path)
    if p.is_absolute():
        return p

    text = str(run_path).strip()
    if not text:
        base_dir = pathlib.Path(results_base_dir or os.getcwd())
        return base_dir

    base_dir = pathlib.Path(results_base_dir or os.getcwd())
    base_parts = base_dir.parts
    path_parts = pathlib.Path(text).parts

    cwd_candidate = pathlib.Path(os.getcwd()) / pathlib.Path(text)
    if cwd_candidate.exists():
        return cwd_candidate

    # If results_base_dir already points at .../searching_results, avoid building
    # .../searching_results/searching_results/<run> when the incoming run_path also
    # starts with searching_results/.
    if path_parts and path_parts[0] == "searching_results" and "searching_results" in base_parts:
        while path_parts and path_parts[0] == "searching_results":
            path_parts = path_parts[1:]
        return base_dir.joinpath(*path_parts)

    return base_dir / pathlib.Path(text)

_VECTOR_REGISTRY: Dict[str, FAISS] = {}
_REGISTRY_LOCK = threading.Lock()

# ContextVar and mechanical query generator shared with searching tool
from searching_tool import _SESSION_DIR_CVAR, _generate_mechanical_query_batch

# ---- (Optional) deep finder retained as a fallback utility ----
def _deep_find_session_dir(obj: Any, visited: Set[int] | None = None, depth: int = 0, max_depth: int = 7) -> Optional[str]:
    if obj is None or depth > max_depth:
        return None
    if visited is None:
        visited = set()
    oid = id(obj)
    if oid in visited:
        return None
    visited.add(oid)

    if isinstance(obj, (str, os.PathLike)):
        s = os.fspath(obj)
        if not s:
            return None
        if os.sep in s or (os.altsep and os.altsep in s):
            return s
        if s.startswith("SSD::"):
            cand = s.split("SSD::", 1)[1].strip()
            return cand or None
        if s.startswith("search_session_dir="):
            cand = s.split("search_session_dir=", 1)[1].strip()
            return cand or None
        return None

    if isinstance(obj, Mapping):
        if "search_session_dir" in obj:
            got = _deep_find_session_dir(obj.get("search_session_dir"), visited, depth+1, max_depth)
            if got:
                return got
        for key in ("tags",):
            if key in obj:
                got = _deep_find_session_dir(obj.get(key), visited, depth+1, max_depth)
                if got:
                    return got
        for key in ("configurable", "kwargs", "metadata", "data", "config", "callbacks"):
            if key in obj:
                got = _deep_find_session_dir(obj.get(key), visited, depth+1, max_depth)
                if got:
                    return got
        for v in obj.values():
            got = _deep_find_session_dir(v, visited, depth+1, max_depth)
            if got:
                return got
        return None

    if isinstance(obj, Iterable) and not isinstance(obj, (bytes, bytearray)):
        for it in obj:
            got = _deep_find_session_dir(it, visited, depth+1, max_depth)
            if got:
                return got
        return None

    for attr in ("config", "configurable", "kwargs", "metadata", "data", "value",
                 "parent_run", "run_manager", "callbacks", "invocation_params"):
        if hasattr(obj, attr):
            try:
                got = _deep_find_session_dir(getattr(obj, attr), visited, depth+1, max_depth)
                if got:
                    return got
            except Exception:
                pass

    try:
        d = vars(obj)
        if isinstance(d, dict):
            return _deep_find_session_dir(d, visited, depth+1, max_depth)
    except Exception:
        pass

    return None

def _iter_paper_jsons(run_dir: str) -> List[pathlib.Path]:
    rd = pathlib.Path(run_dir)
    if not rd.exists():
        return []
    return sorted([p for p in rd.glob("*.json") if p.is_file() and p.suffix == ".json"])


def _parse_json_result(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {"error": True, "message": raw}


def _build_bm25_retriever(all_docs: List[Document], k_fetch: int):
    try:
        bm25_retriever = BM25Retriever.from_documents(all_docs)
    except ModuleNotFoundError as exc:
        missing_name = getattr(exc, "name", "") or ""
        if missing_name == "rank_bm25":
            log.warning("BM25 backend unavailable because rank_bm25 is not installed. Falling back to vector retrieval.")
            return None
        raise
    bm25_retriever.k = k_fetch
    return bm25_retriever

_GLOBAL_EMBEDDINGS = None
_EMBEDDINGS_LOCK = threading.Lock()

def _load_embeddings():
    global _GLOBAL_EMBEDDINGS
    with _EMBEDDINGS_LOCK:
        if _GLOBAL_EMBEDDINGS is None:
            _GLOBAL_EMBEDDINGS = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
        return _GLOBAL_EMBEDDINGS

_GLOBAL_CROSS_ENCODER = None
_CROSS_ENCODER_LOCK = threading.Lock()

def _load_cross_encoder():
    global _GLOBAL_CROSS_ENCODER
    with _CROSS_ENCODER_LOCK:
        if _GLOBAL_CROSS_ENCODER is None and CrossEncoder:
            try:
                device = FULLTEXT_RERANK_DEVICE
                if not device:
                    device = "cuda" if torch and torch.cuda.is_available() else "cpu"
                _GLOBAL_CROSS_ENCODER = CrossEncoder(FULLTEXT_RERANK_MODEL, device=device)
                log.info(f"Loaded cross-encoder reranker: {FULLTEXT_RERANK_MODEL} on {device}")
            except Exception as e:
                log.warning(f"Failed to load cross-encoder '{FULLTEXT_RERANK_MODEL}': {e}")
                if FULLTEXT_RERANK_FALLBACK_MODEL and FULLTEXT_RERANK_FALLBACK_MODEL != FULLTEXT_RERANK_MODEL:
                    try:
                        device = FULLTEXT_RERANK_DEVICE
                        if not device:
                            device = "cuda" if torch and torch.cuda.is_available() else "cpu"
                        _GLOBAL_CROSS_ENCODER = CrossEncoder(FULLTEXT_RERANK_FALLBACK_MODEL, device=device)
                        log.info(f"Loaded fallback cross-encoder reranker: {FULLTEXT_RERANK_FALLBACK_MODEL} on {device}")
                    except Exception as fallback_error:
                        log.warning(f"Failed to load fallback cross-encoder '{FULLTEXT_RERANK_FALLBACK_MODEL}': {fallback_error}")
        return _GLOBAL_CROSS_ENCODER

def _split_text(text: str, chunk_size: int, chunk_overlap: int, by_paragraph: bool) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    def _merge_short_chunks(chunks: List[str], min_chars: int = 80) -> List[str]:
        merged: List[str] = []
        pending = ""
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            if len(chunk) < min_chars:
                pending = f"{pending}\n\n{chunk}".strip() if pending else chunk
                continue
            if pending:
                chunk = f"{pending}\n\n{chunk}"
                pending = ""
            merged.append(chunk)
        if pending:
            if merged:
                merged[-1] = f"{merged[-1]}\n\n{pending}"
            else:
                merged.append(pending)
        return merged

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " "],
        length_function=len,
    )

    if by_paragraph:
        paragraphs = [blk.strip() for blk in re.split(r"\n\s*\n", text) if blk.strip()]
        combined_paragraphs: List[str] = []
        i = 0
        min_paragraph_chars = 120
        while i < len(paragraphs):
            para = paragraphs[i]
            while len(para) < min_paragraph_chars and (i + 1) < len(paragraphs):
                i += 1
                para = f"{para}\n\n{paragraphs[i]}"
            combined_paragraphs.append(para)
            i += 1

        chunks: List[str] = []
        for para in combined_paragraphs:
            chunks.extend(splitter.split_text(para))
        return _merge_short_chunks(chunks)

    chunks = splitter.split_text(text)
    return _merge_short_chunks(chunks)


def _is_trivial_metadata_chunk(text: str, min_substantive_chars: int = FULLTEXT_INDEX_MIN_SUBSTANTIVE_CHARS) -> bool:
    raw = (text or "").strip()
    if not raw:
        return True

    normalized = re.sub(r"\s+", " ", raw)
    lower = normalized.casefold()

    # Reject obvious metadata stubs and ultra-short placeholder content.
    if len(normalized) < 80:
        return True

    metadata_markers = (
        "title:",
        "year:",
        "authors:",
        "journal:",
        "doi:",
        "pmid:",
        "related literature",
        "supplementary material",
        "chemical context",
        "experimental",
    )
    marker_hits = sum(1 for marker in metadata_markers if marker in lower)
    if marker_hits >= 2 and len(normalized) < 300:
        return True

    letters = sum(ch.isalpha() for ch in normalized)
    if letters < min_substantive_chars:
        return True

    # Prefer sentence-like prose over title/header fragments.
    sentence_punct = normalized.count(".") + normalized.count(";") + normalized.count(":")
    word_count = len(re.findall(r"\b\w+\b", normalized))
    if sentence_punct == 0 and word_count < 35:
        return True

    return False


def _normalize_match_text(text: str) -> str:
    text = (text or "").casefold()
    text = text.replace("\u00ad", "")
    text = re.sub(r"[\(\)\[\]\{\},;:]", " ", text)
    text = re.sub(r"[-_/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# -------------------- Tool 1: Build index --------------------
class FullTextIndexInput(BaseModel):
    run_path: str = Field(..., description="Path to the run directory (e.g., searching_results/run_YYYYmmdd_HHMMSS[_idx]) or any file inside it.")
    chunk_size: int = Field(FULLTEXT_INDEX_DEFAULT_CHUNK_SIZE, ge=200, le=4000, description="Characters per chunk.")
    chunk_overlap: int = Field(FULLTEXT_INDEX_DEFAULT_CHUNK_OVERLAP, ge=0, le=1000, description="Overlap between chunks.")
    by_paragraph: bool = Field(True, description="If true, split by paragraphs before chunking.")
    persist: bool = Field(True, description="If true, persist FAISS index files in the run directory.")

class FullTextIndexTool(BaseTool):
    name: str = "fulltext_index"
    description: str = (
        "Load saved paper JSON files (with 'full_text') from a search run, split into chunks, "
        "embed, and build a FAISS vector index for retrieval."
    )
    args_schema: Type[BaseModel] = FullTextIndexInput
    results_base_dir: str = None

    def __init__(self, results_base_dir: str = None, **data):
        super().__init__(**(data or {}))
        self.results_base_dir = str(results_base_dir) if results_base_dir else None

    @staticmethod
    def set_session_dir(path: Optional[str]) -> None:
        _SESSION_DIR_CVAR.set(path)

    def _resolve_run_dir(self, run_path: str) -> str:
        base_path = _normalize_run_path_input(run_path, self.results_base_dir)
        resolved_path = base_path.resolve()
        if resolved_path.is_file():
            return str(resolved_path.parent)
        return str(resolved_path)

    def _run(
        self,
        run_path: str,
        chunk_size: int = FULLTEXT_INDEX_DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = FULLTEXT_INDEX_DEFAULT_CHUNK_OVERLAP,
        by_paragraph: bool = True,
        persist: bool = True,
        config: Optional[RunnableConfig] = None,
        **kwargs,
    ) -> str:
        try:
            # ContextVar first (authoritative)
            session_dir = _SESSION_DIR_CVAR.get()
            if not session_dir and config is not None:
                session_dir = _deep_find_session_dir(config)
            if not session_dir and "config" in kwargs:
                session_dir = _deep_find_session_dir(kwargs["config"])
            run_manager = kwargs.get("run_manager")
            if not session_dir and run_manager is not None:
                session_dir = _deep_find_session_dir(run_manager)

            path_to_index = session_dir or run_path
            if not path_to_index:
                return json.dumps({"error": True, "message": "No run_path specified and search_session_dir not in config/callback."})

            run_dir = self._resolve_run_dir(path_to_index)
        except Exception as e:
            return json.dumps({"error": True, "message": f"Path resolution error: {e}"})

        papers = _iter_paper_jsons(run_dir)
        if not papers:
            return json.dumps({
                "error": False,
                "message": f"No paper JSON files found in {run_dir}. Nothing to index.",
                "run_dir": run_dir,
                "docs_indexed": 0,
                "papers": 0,
                "persisted": False,
                "index_path": ""
            })
        
        docs: List[Document] = []
        for fp in papers:
            try:
                data = json.loads(pathlib.Path(fp).read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"Failed to read {fp}: {e}")
                continue
            title = data.get("title", "")
            meta = {
                "title": title,
                "source": data.get("source", ""),
                "pubdate": data.get("pubdate", ""),
                "doi": data.get("doi", ""),
                "pmid": (data.get("ids", {}) or {}).get("pmid", ""),
                "arxiv": (data.get("ids", {}) or {}).get("arxiv", ""),
                "path": str(fp),
            }
            sections = data.get("sections")
            abstract_only = bool(data.get("abstract_only"))
            offline_chunk_only = bool(data.get("offline_chunk_only"))

            indexed_any = False
            if isinstance(sections, list) and sections:
                section_counter = 0
                for section_idx, section in enumerate(sections):
                    if not isinstance(section, dict):
                        continue
                    section_title = str(section.get("title") or "").strip()
                    section_text = str(section.get("text") or "").strip()
                    if not section_text:
                        continue
                    chunks = _split_text(section_text, chunk_size, chunk_overlap, by_paragraph)
                    section_type = _infer_section_type(section_title)
                    for chunk_idx, ch in enumerate(chunks):
                        if _is_trivial_metadata_chunk(ch):
                            continue
                        dmeta = dict(meta)
                        dmeta["chunk_id"] = f"{pathlib.Path(fp).stem}:{section_idx}:{chunk_idx}"
                        dmeta["section_title"] = section_title
                        dmeta["section_type"] = section_type
                        docs.append(Document(page_content=ch, metadata=dmeta))
                        section_counter += 1
                indexed_any = section_counter > 0

            if indexed_any:
                continue

            full_text = (data.get("full_text") or "").strip()
            if not full_text:
                continue
            chunks = _split_text(full_text, chunk_size, chunk_overlap, by_paragraph)
            section_type = _infer_section_type("", abstract_only=abstract_only, offline_chunk_only=offline_chunk_only)
            for i, ch in enumerate(chunks):
                if _is_trivial_metadata_chunk(ch):
                    continue
                dmeta = dict(meta)
                dmeta["chunk_id"] = f"{pathlib.Path(fp).stem}:{i}"
                dmeta["section_title"] = "Abstract" if abstract_only else ("Offline Chunk" if offline_chunk_only else "")
                dmeta["section_type"] = section_type
                docs.append(Document(page_content=ch, metadata=dmeta))

        if not docs:
            return json.dumps({"error": True, "message": f"No full_text content to index in {run_dir}."})

        embeddings = _load_embeddings()
        vectordb = FAISS.from_documents(docs, embeddings)

        if persist:
            idx_dir = pathlib.Path(run_dir) / "faiss_index"
            idx_dir.mkdir(exist_ok=True)
            vectordb.save_local(str(idx_dir))
        with _REGISTRY_LOCK:
            _VECTOR_REGISTRY[run_dir] = vectordb

        return json.dumps({
            "error": False,
            "run_dir": run_dir,
            "docs_indexed": len(docs),
            "papers": len(papers),
            "persisted": persist,
            "index_path": str(pathlib.Path(run_dir) / "faiss_index") if persist else "",
        })

# -------------------- Tool 2: Query index --------------------
class FullTextQueryInput(BaseModel):
    run_path: str = Field(..., description="Run directory or any file within it.")
    query: Optional[str | List[str]] = Field(None, description="Fallback-only raw query text. Prefer identity_terms + content_terms when the target entity is known.")
    identity_terms: Optional[List[str]] = Field(None, description="Preferred structured input. Entity names or strong textual synonyms to combine mechanically into extraction queries.")
    content_terms: Optional[List[str]] = Field(None, description="Preferred structured input. Short criterion-focused content/context terms to combine with identity_terms.")
    k: int = Field(FULLTEXT_QUERY_DEFAULT_K, ge=1, le=100, description="Number of top snippets to return.")

class FullTextQueryTool(BaseTool):
    name: str = "fulltext_query"
    description: str = (
        "Query a previously built FAISS index of full texts from a search run. "
        "Prefer structured calls with identity_terms + content_terms; use raw query only as fallback. "
        "Returns top-k text snippets with metadata for grounding and citation."
    )
    args_schema: Type[BaseModel] = FullTextQueryInput
    results_base_dir: Optional[str] = None

    def __init__(self, results_base_dir: Optional[str] = None, **data):
        super().__init__(**(data or {}))
        self.results_base_dir = str(results_base_dir) if results_base_dir else None

    @staticmethod
    def set_session_dir(path: Optional[str]) -> None:
        _SESSION_DIR_CVAR.set(path)

    def _resolve_run_dir(self, run_path: str) -> str:
        base_path = _normalize_run_path_input(run_path, self.results_base_dir)
        resolved_path = base_path.resolve()
        if resolved_path.is_file():
            return str(resolved_path.parent)
        return str(resolved_path)

    def _load_index(self, run_dir: str) -> Optional[FAISS]:
        if run_dir in _VECTOR_REGISTRY:
            return _VECTOR_REGISTRY[run_dir]
        idx_dir = pathlib.Path(run_dir) / "faiss_index"
        if idx_dir.exists():
            try:
                embeddings = _load_embeddings()
                vs = FAISS.load_local(str(idx_dir), embeddings, allow_dangerous_deserialization=True)
                with _REGISTRY_LOCK:
                    _VECTOR_REGISTRY[run_dir] = vs
                return vs
            except Exception as e:
                log.warning(f"Failed to load FAISS from {idx_dir}: {e}")
        return None

    def _ensure_index(self, run_dir: str, config: Optional[RunnableConfig] = None) -> tuple[Optional[FAISS], Dict[str, Any] | None]:
        vectordb = self._load_index(run_dir)
        if vectordb is not None:
            return vectordb, None

        bootstrap_tool = FullTextIndexTool(results_base_dir=self.results_base_dir)
        build_raw = bootstrap_tool._run(run_path=run_dir, config=config)
        build_result = _parse_json_result(build_raw)
        vectordb = self._load_index(run_dir)
        return vectordb, build_result

    def _run(
        self, 
        run_path: str, 
        query: Optional[str | List[str]] = None,
        identity_terms: Optional[List[str]] = None,
        content_terms: Optional[List[str]] = None,
        k: int = FULLTEXT_QUERY_DEFAULT_K, 
        config: Optional[RunnableConfig] = None,
        **kwargs
    ) -> str:
        try:
            session_dir = _SESSION_DIR_CVAR.get()
            if not session_dir and config is not None:
                session_dir = _deep_find_session_dir(config)
            if not session_dir and "config" in kwargs:
                session_dir = _deep_find_session_dir(kwargs["config"])
            run_manager = kwargs.get("run_manager")
            if not session_dir and run_manager is not None:
                session_dir = _deep_find_session_dir(run_manager)

            path_to_query = session_dir or run_path
            if not path_to_query:
                return json.dumps({"error": True, "message": "No run_path specified and search_session_dir not in config/callback."})
            run_dir = self._resolve_run_dir(path_to_query)
        except Exception as e:
            return json.dumps({"error": True, "message": f"Path resolution error: {e}"})

        vectordb, build_result = self._ensure_index(run_dir, config=config)
        if not vectordb:
            message = f"No index found for {run_dir}."
            if build_result:
                message = build_result.get("message") or message
                if build_result.get("error") is False:
                    return json.dumps({
                        "error": False,
                        "run_dir": run_dir,
                        "k": k,
                        "results": [],
                        "message": message,
                    })
            return json.dumps({"error": True, "message": message})

        query_batch = _generate_mechanical_query_batch(
            query=query,
            identity_terms=identity_terms,
            context_terms=content_terms,
            max_queries=FULLTEXT_QUERY_MAX_QUERIES,
        )
        if not query_batch:
            return json.dumps({"error": True, "message": "No query, identity_terms, or content_terms provided."})

        try:
            # --- HYBRID SEARCH UPGRADE ---
            # 1. Recover documents from FAISS docstore
            if hasattr(vectordb, "docstore") and hasattr(vectordb.docstore, "_dict"):
                all_docs = list(vectordb.docstore._dict.values())
            else:
                all_docs = []

            k_fetch = max(FULLTEXT_QUERY_MIN_FETCH, k * FULLTEXT_QUERY_FETCH_MULTIPLIER)
            aggregated: Dict[str, tuple[Document, float]] = {}

            for query_text_raw in query_batch:
                query_text = str(query_text_raw or "").strip()
                if not query_text:
                    continue
                try:
                    if all_docs and len(all_docs) > 0:
                        faiss_retriever = vectordb.as_retriever(search_kwargs={"k": k_fetch})
                        bm25_retriever = _build_bm25_retriever(all_docs, k_fetch)

                        if bm25_retriever is not None:
                            ensemble_retriever = EnsembleRetriever(
                                retrievers=[bm25_retriever, faiss_retriever],
                                weights=[0.5, 0.5]
                            )
                            retrieved_docs = ensemble_retriever.invoke(query_text)
                        else:
                            retrieved_docs = faiss_retriever.invoke(query_text)

                        docs_and_scores = [(d, 1.0) for d in retrieved_docs]
                    else:
                        docs_and_scores = vectordb.similarity_search_with_score(query_text, k=k_fetch)

                    reranker = _load_cross_encoder()
                    if reranker and docs_and_scores:
                        pairs = [[query_text, d.page_content] for d, _ in docs_and_scores]
                        try:
                            scores = reranker.predict(pairs)
                            docs_and_scores = [(doc, float(scores[i])) for i, (doc, _) in enumerate(docs_and_scores)]
                        except Exception as e:
                            log.warning(f"Reranking failed for query '{query_text}': {e}")

                    for doc, score in docs_and_scores:
                        md = doc.metadata or {}
                        key = (
                            md.get("chunk_id")
                            or md.get("path")
                            or f"{md.get('title','')}::{doc.page_content[:120]}"
                        )
                        existing = aggregated.get(key)
                        if existing is None or score > existing[1]:
                            aggregated[key] = (doc, float(score))
                except Exception as q_err:
                    log.warning(f"Hybrid query failed for '{query_text}' ({q_err}); using vector fallback for this query.")
                    try:
                        fallback_docs = vectordb.similarity_search_with_score(query_text, k=k_fetch)
                        for doc, score in fallback_docs:
                            md = doc.metadata or {}
                            key = (
                                md.get("chunk_id")
                                or md.get("path")
                                or f"{md.get('title','')}::{doc.page_content[:120]}"
                            )
                            existing = aggregated.get(key)
                            if existing is None or float(score) > existing[1]:
                                aggregated[key] = (doc, float(score))
                    except Exception:
                        continue

            ranked_entries: List[tuple[float, Document]] = []
            for doc, score in aggregated.values():
                ranked_entries.append((float(score), doc))

            ranked_entries.sort(key=lambda x: x[0], reverse=True)
            docs_and_scores = [(doc, score) for score, doc in ranked_entries[:k]]

        except Exception as e:
            log.warning(f"Hybrid search failed ({e}), falling back to vector only.")
            try:
                fallback_query = query_batch[0]
                fallback_docs_and_scores = vectordb.similarity_search_with_score(fallback_query, k=k)
                docs_and_scores = sorted(fallback_docs_and_scores, key=lambda x: x[1], reverse=True)
            except Exception as e2:
                 return json.dumps({"error": True, "message": f"Search failed: {e2}"})

        results: List[Dict[str, Any]] = []
        for item in docs_and_scores:
            doc, score = item
            md = doc.metadata or {}
            snippet = re.sub(r"\s+", " ", doc.page_content.strip())
            results.append({
                "score": float(score),
                "text": snippet,
                "title": md.get("title", ""),
                "source": md.get("source", ""),
                "pubdate": md.get("pubdate", ""),
                "doi": md.get("doi", ""),
                "pmid": md.get("pmid", ""),
                "arxiv": md.get("arxiv", ""),
                "path": md.get("path", ""),
                "chunk_id": md.get("chunk_id", ""),
                "section_title": md.get("section_title", ""),
                "section_type": md.get("section_type", ""),
            })

        return json.dumps({"error": False, "run_dir": run_dir, "k": k, "generated_queries": query_batch, "results": results})
