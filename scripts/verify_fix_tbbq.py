
import sys
import os
import logging
from pathlib import Path
from typing import List, Dict

# Setup paths
current_dir = os.getcwd()
sys.path.append(os.path.join(current_dir, 'code'))

from searching_tool import FullTextJournalSearchTool
import inspect

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True,
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("verify_tbbq")

def inspect_code():
    print(f"\n[DEBUG] Loaded searching_tool from: {sys.modules['searching_tool'].__file__}")
    source = inspect.getsource(FullTextJournalSearchTool._run)
    if "DEBUG: Checking Rerank Block" in source:
        print("[DEBUG] ✅ 'Checking Rerank Block' found in source code.")
    else:
        print("[DEBUG] ❌ 'Checking Rerank Block' NOT found in source code!")
    if "papers = self._rerank_results(queries, papers)" in source:
        print("[DEBUG] ✅ Fix (queries) found in source code.")
    elif "queries[0]" in source:
        print("[DEBUG] ❌ Reverted Code (queries[0]) found in source code!")

class DebugSearchTool(FullTextJournalSearchTool):
    def _rerank_results(self, query: str | List[str], papers: List[Dict]) -> List[Dict]:
        print(f"\n[DEBUG] Reranking {len(papers)} papers...")
        # Check if target is present BEFORE reranking
        found = False
        for p in papers:
            if "Solid phase extraction" in p.get("title", "") or "TBBQ" in p.get("title", ""):
                print(f"[DEBUG] FOUND TARGET BEFORE RERANKING: {p.get('title', '')[:100]}")
                found = True
        if not found:
            print("[DEBUG] TARGET NOT FOUND BEFORE RERANKING! (Retrieval Issue?)")
            
        # Call original
        papers = super()._rerank_results(query, papers)
        
        # Check scores
        print("\n[DEBUG] Top 5 Scores:")
        for i, p in enumerate(papers[:5]):
            print(f"  {i+1}. [{p.get('_relevance_score', 0):.4f}] {p.get('title', '')[:80]}")
            
        return papers

def main():
    inspect_code()
    print("Initializing Debug Search Tool...")
    tool = DebugSearchTool(
        include_offline_search=True,
        offline_index_path="/data/chen/GNPS_SIM/pmc_lancedb_index",
        offline_doc_dir="/home/chen/pubmed_corpus/pmc_extracted_text",
        include_pubmed=False, 
        include_eupmc=False,
        include_s2=False
    )

    queries = [
        "2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione", 
        "TBBQ", 
        "Bromanil",
        "Tetrabromo-1,4-benzoquinone"
    ]
    
    print(f"\nRunning Search with Multi-Query: {queries}")
    print("-" * 60)

    results = tool._run(query=queries, max_results=20)
    
    if "Solid phase extraction" in results:
        print("\n\n✅ SUCCESS: The target paper 'Solid phase extraction...' was retrieved!")
    else:
        print("\n\n❌ FAILURE: The target paper was NOT found.")

if __name__ == "__main__":
    main()
