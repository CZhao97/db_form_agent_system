from __future__ import annotations
import os, re, json, pathlib, logging
from typing import List, Dict, Optional, Any, Type

from pydantic import BaseModel, Field
from langchain.tools import BaseTool

# Embeddings & Vector store (LangChain)
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

log = logging.getLogger("fulltext_vector_tools")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --------- simple in-process registry so indexes survive across tool calls ----------
_VECTOR_REGISTRY: Dict[str, FAISS] = {}  # key: run_dir absolute path -> FAISS store


# -------------------- Utility helpers --------------------
def _detect_run_dir(path_like: str) -> str:
    """
    Accept a run_dir OR any file path inside it and normalize to the run_dir path.
    Run dirs look like: searching_results/run_YYYYmmdd_HHMMSS[_idx]
    """
    p = pathlib.Path(path_like).resolve()
    if p.is_dir() and p.name.startswith("run_"):
        return str(p)
    # Walk up to find run_*
    for parent in [p] + list(p.parents):
        if parent.is_dir() and parent.name.startswith("run_") and parent.parent.name == "searching_results":
            return str(parent)
    # Fallback: if someone passed 'searching_results/run_...' string that doesn't exist yet
    if "searching_results" in str(p).replace("\\","/"):
        return str(p)
    raise ValueError(f"Could not locate a run_* directory from: {path_like}")

def _iter_paper_jsons(run_dir: str) -> List[pathlib.Path]:
    rd = pathlib.Path(run_dir)
    if not rd.exists():
        return []
    return sorted([p for p in rd.glob("*.json") if p.is_file() and p.suffix == ".json"])

def _load_embeddings():
    # Local, no-API embeddings (≈384-dim)
    return SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

def _split_text(text: str, chunk_size: int, chunk_overlap: int, by_paragraph: bool) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    if by_paragraph:
        # Split on blank lines; keep reasonably sized chunks using a splitter after
        paragraphs = [blk.strip() for blk in re.split(r"\n\s*\n", text) if blk.strip()]
        # Re-pack long paragraphs if needed
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " "],
            length_function=len,
        )
        chunks: List[str] = []
        for para in paragraphs:
            chunks.extend(splitter.split_text(para))
        return chunks
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " "],
            length_function=len,
        )
        return splitter.split_text(text)


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

    def _run(
        self,
        run_path: str,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        by_paragraph: bool = True,
        persist: bool = True,
    ) -> str:
        try:
            run_dir = _detect_run_dir(run_path)
        except Exception as e:
            return json.dumps({"error": True, "message": str(e)})

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

        # persist + cache
        if persist:
            idx_dir = pathlib.Path(run_dir) / "faiss_index"
            idx_dir.mkdir(exist_ok=True)
            vectordb.save_local(str(idx_dir))
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

    def _load_index(self, run_dir: str) -> Optional[FAISS]:
        # 1) in-memory cache
        if run_dir in _VECTOR_REGISTRY:
            return _VECTOR_REGISTRY[run_dir]
        # 2) on-disk persisted
        idx_dir = pathlib.Path(run_dir) / "faiss_index"
        if idx_dir.exists():
            try:
                embeddings = _load_embeddings()
                vs = FAISS.load_local(str(idx_dir), embeddings, allow_dangerous_deserialization=True)
                _VECTOR_REGISTRY[run_dir] = vs
                return vs
            except Exception as e:
                log.warning(f"Failed to load FAISS from {idx_dir}: {e}")
        return None

    def _run(self, run_path: str, query: str, k: int = 5) -> str:
        try:
            run_dir = _detect_run_dir(run_path)
        except Exception as e:
            return json.dumps({"error": True, "message": str(e)})

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
            snippet = doc.page_content.strip()
            # Compact the snippet a bit
            snippet = re.sub(r"\s+", " ", snippet)
            results.append({
                "score": float(score),
                "text": snippet,  # keep it readable
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
