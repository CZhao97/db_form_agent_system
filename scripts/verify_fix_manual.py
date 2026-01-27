
import sys
import os
import logging
import inspect
from typing import List, Dict

# Setup paths
current_dir = os.getcwd()
sys.path.append(os.path.join(current_dir, 'code'))

from searching_tool import FullTextJournalSearchTool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True,
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("verify_tbbq")

def main():
    print("Initializing Debug Search Tool...")
    tool = FullTextJournalSearchTool(
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

    # DIRECT CALL TO INTERNAL HELPERS TO BYPASS _RUN CONFUSION
    # We want to check:
    # 1. Retrieval
    # 2. Reranking
    
    papers = []
    print("--- Step 1: Manual Retrieval ---")
    for q in queries:
        print(f"Searching for: {q}")
        res = tool._search_offline_db(q, max_results=50)
        print(f"  Got {len(res)} results.")
        papers.extend(res)
    
    # Deduplicate by title/doi roughly
    seen = set()
    unique_papers = []
    for p in papers:
        k = p.get('title', '')
        if k not in seen:
            seen.add(k)
            unique_papers.append(p)
    papers = unique_papers
    print(f"Total Unique Retrieved: {len(papers)}")
    
    target_found = False
    for p in papers:
        if "Solid phase extraction" in p.get("title", ""):
            print(f"FOUND TARGET: {p.get('title')}")
            target_found = True
            
    if not target_found:
        print("TARGET NOT IN OFFLINE RETRIEVAL RESULTS (Top 37 limit?)")
        
    # 2. Reranking
    print("\n--- Step 2: Manual Reranking ---")
    reranked = tool._rerank_results(queries, papers)
    
    print("Top 5 Reranked:")
    for i, p in enumerate(reranked[:5]):
        print(f"{i+1}. [{p.get('_relevance_score'):.4f}] {p.get('title')}")
        
    if "Solid phase extraction" in reranked[0].get("title", ""):
        print("\n✅ CONFIRMED: Target paper is #1 after Multi-Query Reranking.")
    else:
        print("\n❌ FAILURE: Target paper is NOT #1.")

if __name__ == "__main__":
    main()
