
from e2e_agent import FullTextJournalSearchTool
import logging
import sys

# Setup logging
logging.basicConfig(level=logging.INFO)

# Initialize tool
# Note: We rely on the defaults but can force behavior if needed via internal flags or just checking output source
tool = FullTextJournalSearchTool(
    results_base_dir="/data/chen/e2e_searching_results_test_offline",
    enable_ner_indexing=True,
    offline_index_path="/data/chen/GNPS_SIM/pmc_lancedb_index"
)

def test_offline(compound_name):
    query = f'"{compound_name}" AND "disinfection byproduct"'
    print(f"\n--- Testing Offline Search for: {compound_name} ---")
    
    # We want to check the offline DB specifically. 
    # The tool's _search_offline_db method is internal, but we can call it if we instantiate the tool.
    # Alternatively, we can run the full tool and check the 'source' field of results.
    
    # Access internal method to test PURE offline behavior without triggering online fallback
    try:
        # Connect to DB first (usually done in _run, but we can call _search_offline_db directly if we setup)
        # However, _search_offline_db needs the 'offline_table' which is initialized in _run or globally.
        # It's better to use the tool's public method but inspect the results.
        
        # Actually, let's use the helper function logic directly or the check script logic?
        # The user likely wants to know if the AGENT tool works in offline mode.
        # But the tool is designed to be hybrid.
        
        # Let's assume the user means "Does the offline component return hits?".
        # My previous 'check_offline_db.py' WAS a test of offline search. 
        # But this script will test the Tool's integration.
        
        # We can force the tool to skip online by mocking or just checking the logs/results.
        # Let's call the internal method _search_offline_db if possible, passing the query.
        
        # Re-initialize DB connection manually if needed since it's inside _run usually?
        # No, _search_offline_db expects 'offline_table' as argument.
        
        import lancedb
        db = lancedb.connect(tool.offline_index_path)
        tbl = db.open_table("papers_index")
        
        # NOW call the internal method
        # _search_offline_db(self, query, offline_table, limit=50)
        # Note: clean_query logic is inside _run, so we pass raw query?
        # The method expects 'query' and 'offline_table'.
        
        # Correct Signature: def _search_offline_db(self, query: str, limit: int, offline_table, enable_keyword: bool = True)
        # Note: We rely on the defaults which now has enable_keyword=True
        results = tool._search_offline_db(query, 50, tbl)
        
        print(f"Results found: {len(results)}")
        for r in results[:10]:
            print(f" - Title: {r.get('title', 'No Title')}")
            print(f" - Source: {r.get('source')}")
            # The tool puts search_method in the DataFrame but converts to dict. 
            # I need to ensure _search_offline_db preserves it in the dict output.
            # Looking at the code, res_vec = df_vec.to_dict("records"), it preserves all columns.
            print(f" - Method: {r.get('search_method', 'N/A')}")
            print(f" - Distance: {r.get('_distance', 'N/A')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_offline("Iodoacetic acid") # Should have hits
    test_offline("Bromonaproxen")   # Should have 0 hits (due to filter)
