
import sys
import os
import logging
from pprint import pprint

# Ensure code is in path
sys.path.append(os.path.abspath("code"))

from searching_tool import FullTextJournalSearchTool

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_unified_search():
    print("Initializing Search Tool...")
    tool = FullTextJournalSearchTool(
        results_base_dir="verification_results",
        offline_index_path="/data/chen/GNPS_SIM/pmc_lancedb_index",
        # Turn off online sources to verify offline isolation
        include_pubmed=False,
        include_eupmc=False,
        include_s2=False,
        include_preprints=False,
        include_offline_search=True
    )
    # FORCE PATH to ensure correct one is used
    tool.offline_index_path = "/data/chen/GNPS_SIM/pmc_lancedb_index"
    print(f"Tool configured with path: {tool.offline_index_path}")
    
    query = "brucellosis" # Known to exist in sample
    print(f"\nSearching for '{query}' (Offline Only)...")
    
    # Run Search
    # Note: enable_offline_keyword defaults to False, so this tests Vector path
    result_str = tool._run(query, max_results=2)
    
    print("\nSearch Result Summary:")
    print(result_str)
    
    # Verify we hit the offline DB
    # The output string usually says "Total Papers Found: X".
    # We want to check the actual saved data or logs, but _run returns a summary string.
    # However, duplicates are removed.
    
    # We can invoke _search_offline_db directly to see raw output
    print(f"\nDirectly invoking _search_offline_db for '{query}'...")
    
    # Manually connect since 'offline_table' is local to _run
    import lancedb
    print(f"Connecting to DB at: {tool.offline_index_path}")
    db = lancedb.connect(tool.offline_index_path)
    print(f"Available tables: {db.table_names()}")
    tbl = db.open_table("papers_index")
    
    offline_results = tool._search_offline_db(query, limit=2, offline_table=tbl)
    
    found = len(offline_results) > 0
    print(f"Direct Offline Hits: {len(offline_results)}")
    if found:
        print("Sample Result:")
        pprint(offline_results[0])
        print(f"Source: {offline_results[0].get('source')}")
        
    if found and offline_results[0].get('source') == "offline_db":
        print("\nSUCCESS: Verified Unified Search (Offline Hit).")
    else:
        print("\nFAILURE: Did not find offline results.")

if __name__ == "__main__":
    test_unified_search()
