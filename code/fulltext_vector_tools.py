from __future__ import annotations
import os, re, json, pathlib, logging, threading
from typing import List, Dict, Optional, Any, Type, Set
from collections.abc import Mapping, Iterable
from contextvars import ContextVar

from pydantic import BaseModel, Field
from langchain.tools import BaseTool

from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.runnables import RunnableConfig

log = logging.getLogger("fulltext_vector_tools")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

_VECTOR_REGISTRY: Dict[str, FAISS] = {}
_REGISTRY_LOCK = threading.Lock()

# ContextVar shared with searching tool to carry session dir
_SESSION_DIR_CVAR: ContextVar[Optional[str]] = ContextVar("SEARCH_SESSION_DIR", default=None)

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

def _load_embeddings():
    return SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

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

# -------------------- Tool 1: Build index --------------------
class FullTextIndexInput(BaseModel):
    run_path: str = Field(..., description="Path to the run directory (e.g., searching_results/run_YYYYmmdd_HHMMSS[_idx]) or any file inside it.")
    chunk_size: int = Field(800, ge=200, le=4000, description="Characters per chunk.")
    chunk_overlap: int = Field(120, ge=0, le=1000, description="Overlap between chunks.")
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
        p = pathlib.Path(run_path)
        if p.is_absolute():
            base_path = p
        else:
            base_dir = self.results_base_dir or os.getcwd()
            base_path = pathlib.Path(base_dir) / run_path
        resolved_path = base_path.resolve()
        if resolved_path.is_file():
            return str(resolved_path.parent)
        return str(resolved_path)

    def _run(
        self,
        run_path: str,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
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
            return json.dumps({"error": True, "message": f"No paper JSON files found in {run_dir}."})
        
        docs: List[Document] = []
        for fp in papers:
            try:
                data = json.loads(pathlib.Path(fp).read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"Failed to read {fp}: {e}")
                continue
            full_text = (data.get("full_text") or "").strip()
            if not full_text:
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
            chunks = _split_text(full_text, chunk_size, chunk_overlap, by_paragraph)
            for i, ch in enumerate(chunks):
                dmeta = dict(meta)
                dmeta["chunk_id"] = f"{pathlib.Path(fp).stem}:{i}"
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
    query: str = Field(..., description="Natural-language question to retrieve evidence.")
    k: int = Field(20, ge=1, le=100, description="Number of top snippets to return.")

class FullTextQueryTool(BaseTool):
    name: str = "fulltext_query"
    description: str = (
        "Query a previously built FAISS index of full texts from a search run. "
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
        p = pathlib.Path(run_path)
        if p.is_absolute():
            base_path = p
        else:
            base_dir = self.results_base_dir or os.getcwd()
            base_path = pathlib.Path(base_dir) / run_path
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

    def _run(
        self, 
        run_path: str, 
        query: str, 
        k: int = 5, 
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

        vectordb = self._load_index(run_dir)
        if not vectordb:
            return json.dumps({"error": True, "message": f"No index found for {run_dir}. Build it with fulltext_index first."})

        try:
            docs_and_scores = vectordb.similarity_search_with_score(query, k=k)
        except Exception as e:
            return json.dumps({"error": True, "message": f"Search failed: {e}"})

        results: List[Dict[str, Any]] = []
        for doc, score in docs_and_scores:
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
            })

        return json.dumps({"error": False, "run_dir": run_dir, "k": k, "results": results})
