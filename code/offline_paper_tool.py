from __future__ import annotations
import os
import json
import logging
import pathlib
from typing import List, Dict, Optional, Any, Type
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
import lancedb
from lancedb.rerankers import RRFReranker

log = logging.getLogger("offline_paper_tool")

class OfflinePaperSearchInput(BaseModel):
    query: str = Field(..., description="Natural language query to search in the offline paper database.")
    k: int = Field(5, description="Number of results to return.")
    index_path: Optional[str] = Field(None, description="Path to the LanceDB index directory. Defaults to './pmc_lancedb_index'.")

class OfflinePaperSearchTool(BaseTool):
    name: str = "offline_paper_search"
    description: str = (
        "Search for papers in a pre-built local offline database (LanceDB). "
        "Useful for retrieving information from a large collection of downloaded papers (e.g., PMC) "
        "without needing internet access. Returns text snippets and pre-computed NER entities."
    )
    args_schema: Type[BaseModel] = OfflinePaperSearchInput
    
    _db: Optional[lancedb.DBConnection] = None
    _table: Optional[lancedb.table.Table] = None
    _reranker: Optional[RRFReranker] = None
    _index_path: str = "./pmc_lancedb_index"
    _table_name: str = "papers_index"

    def __init__(self, index_path: str = "./pmc_lancedb_index", **data):
        super().__init__(**data)
        self._index_path = index_path

    def _load_resources(self, index_path: str):
        # Always try to connect if not connected or if path changed
        if self._db is None:
            # Resolve absolute path to avoid CWD issues
            abs_path = os.path.abspath(index_path)
            if not os.path.exists(abs_path):
                # Try relative to the tool file if not found in CWD
                tool_dir = os.path.dirname(os.path.abspath(__file__))
                # Assuming structure is code/offline_paper_tool.py and index is in root/pmc_lancedb_index
                # So we go up one level
                root_dir = os.path.dirname(tool_dir)
                alt_path = os.path.join(root_dir, os.path.basename(index_path))
                
                if os.path.exists(alt_path):
                    abs_path = alt_path
                else:
                    raise ValueError(f"Index path does not exist: {abs_path}. Please run build_offline_db.py first.")
            
            try:
                self._db = lancedb.connect(abs_path)
                if self._table_name not in self._db.table_names():
                     raise ValueError(f"Table '{self._table_name}' not found in database at {abs_path}")
                
                self._table = self._db.open_table(self._table_name)
                self._reranker = RRFReranker()
                
            except Exception as e:
                log.error(f"Failed to load LanceDB: {e}")
                raise

    def _run(self, query: str, k: int = 5, index_path: Optional[str] = None, **kwargs) -> str:
        target_index = index_path or self._index_path
        
        try:
            self._load_resources(target_index)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:
            return json.dumps({"error": f"Error loading index: {str(e)}"})

        try:
            # Perform Hybrid Search
            results_df = (
                self._table.search(query, query_type="hybrid")
                .rerank(self._reranker)
                .limit(k)
                .to_pandas()
            )
            
            if results_df.empty:
                return json.dumps([])

            results = []
            for _, row in results_df.iterrows():
                # Parse NER JSON if present
                ner_data = {}
                if 'ner_results' in row and row['ner_results']:
                    try:
                        ner_data = json.loads(row['ner_results'])
                    except:
                        pass

                results.append({
                    "doc_id": row.get("doc_id", ""),
                    "title": row.get("title", "No Title"),
                    "year": row.get("year", ""),
                    "source": row.get("source", "OfflineDB"),
                    "score": float(row.get("_relevance_score", 0.0)),
                    "text": row.get("text", ""),
                    "ner": ner_data
                })
            
            return json.dumps(results, indent=2)
            
        except Exception as e:
            return json.dumps({"error": f"Error during search: {str(e)}"})
