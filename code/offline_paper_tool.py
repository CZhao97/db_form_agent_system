from __future__ import annotations
import os
import json
import logging
import pathlib
from typing import List, Dict, Optional, Any, Type
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import SentenceTransformerEmbeddings

log = logging.getLogger("offline_paper_tool")

class OfflinePaperSearchInput(BaseModel):
    query: str = Field(..., description="Natural language query to search in the offline paper database.")
    k: int = Field(5, description="Number of results to return.")
    index_path: Optional[str] = Field(None, description="Path to the FAISS index directory. Defaults to './pmc_faiss_index'.")

class OfflinePaperSearchTool(BaseTool):
    name: str = "offline_paper_search"
    description: str = (
        "Search for papers in a pre-built local offline database (FAISS index). "
        "Useful for retrieving information from a large collection of downloaded papers (e.g., PMC, S2ORC) "
        "without needing internet access."
    )
    args_schema: Type[BaseModel] = OfflinePaperSearchInput
    
    _embeddings: Optional[SentenceTransformerEmbeddings] = None
    _vector_store: Optional[FAISS] = None
    _index_path: str = "./pmc_faiss_index"

    def __init__(self, index_path: str = "./pmc_faiss_index", **data):
        super().__init__(**data)
        self._index_path = index_path

    def _load_resources(self, index_path: str):
        if self._vector_store is None:
            if not os.path.exists(index_path):
                raise ValueError(f"Index path does not exist: {index_path}. Please run scripts/build_offline_index.py first.")
            
            if self._embeddings is None:
                self._embeddings = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
            
            try:
                self._vector_store = FAISS.load_local(
                    index_path, 
                    self._embeddings, 
                    allow_dangerous_deserialization=True
                )
            except Exception as e:
                log.error(f"Failed to load FAISS index: {e}")
                raise

    def _run(self, query: str, k: int = 5, index_path: Optional[str] = None, **kwargs) -> str:
        target_index = index_path or self._index_path
        
        try:
            self._load_resources(target_index)
        except ValueError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            return f"Error loading index: {str(e)}"

        try:
            docs_and_scores = self._vector_store.similarity_search_with_score(query, k=k)
            
            results = []
            for doc, score in docs_and_scores:
                meta = doc.metadata
                results.append({
                    "title": meta.get("title", "No Title"),
                    "doi": meta.get("doi", ""),
                    "pmid": meta.get("pmid", ""),
                    "source": meta.get("source", "OfflineDB"),
                    "score": float(score),
                    "snippet": doc.page_content[:500] + "..." if len(doc.page_content) > 500 else doc.page_content
                })
            
            return json.dumps(results, indent=2)
            
        except Exception as e:
            return f"Error during search: {str(e)}"

class OfflinePaperDumpInput(BaseModel):
    limit: int = Field(10, description="Number of documents to return.")
    offset: int = Field(0, description="Start index for pagination.")
    index_path: Optional[str] = Field(None, description="Path to the FAISS index directory.")
    full_text: bool = Field(False, description="Whether to return full text content. If False, returns a snippet.")

class OfflinePaperDumpTool(BaseTool):
    name: str = "offline_paper_dump"
    description: str = (
        "Retrieve raw documents from the offline database (FAISS index) with pagination. "
        "Useful for iterating over all indexed papers to perform batch processing or analysis."
    )
    args_schema: Type[BaseModel] = OfflinePaperDumpInput
    
    _embeddings: Optional[SentenceTransformerEmbeddings] = None
    _vector_store: Optional[FAISS] = None
    _index_path: str = "./pmc_faiss_index"

    def __init__(self, index_path: str = "./pmc_faiss_index", **data):
        super().__init__(**data)
        self._index_path = index_path

    def _load_resources(self, index_path: str):
        if self._vector_store is None:
            if not os.path.exists(index_path):
                raise ValueError(f"Index path does not exist: {index_path}. Please run scripts/build_offline_index.py first.")
            
            if self._embeddings is None:
                self._embeddings = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
            
            try:
                self._vector_store = FAISS.load_local(
                    index_path, 
                    self._embeddings, 
                    allow_dangerous_deserialization=True
                )
            except Exception as e:
                log.error(f"Failed to load FAISS index: {e}")
                raise

    def _run(self, limit: int = 10, offset: int = 0, index_path: Optional[str] = None, full_text: bool = False, **kwargs) -> str:
        target_index = index_path or self._index_path
        
        try:
            self._load_resources(target_index)
        except ValueError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            return f"Error loading index: {str(e)}"

        try:
            # Access internal docstore mapping
            if not hasattr(self._vector_store, 'index_to_docstore_id'):
                 return "Error: Vector store does not support direct access (missing index_to_docstore_id)."
            
            index_to_id = self._vector_store.index_to_docstore_id
            total_docs = len(index_to_id)
            
            if offset >= total_docs:
                return json.dumps({
                    "results": [], 
                    "total": total_docs, 
                    "offset": offset, 
                    "limit": limit,
                    "has_more": False
                })
            
            # Sort indices to ensure stable pagination
            sorted_indices = sorted(index_to_id.keys())
            end = min(offset + limit, total_docs)
            batch_indices = sorted_indices[offset:end]
            
            results = []
            for idx in batch_indices:
                doc_id = index_to_id[idx]
                doc = self._vector_store.docstore.search(doc_id)
                if doc:
                    content = doc.page_content
                    if not full_text and len(content) > 500:
                        content = content[:500] + "..."
                        
                    results.append({
                        "index_id": int(idx), # Convert numpy int to python int if necessary
                        "doc_id": doc_id,
                        "metadata": doc.metadata,
                        "content": content
                    })
            
            return json.dumps({
                "results": results,
                "total": total_docs,
                "offset": offset,
                "limit": limit,
                "has_more": end < total_docs
            }, indent=2)
            
        except Exception as e:
            return f"Error during dump: {str(e)}"
