
import logging
import sys
from pathlib import Path

# Configure path to import agent code
sys.path.append("/home/chen/GNPS_SIM/agent/db_form_agent_system/code")

from searching_tool import FullTextJournalSearchTool

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_online_limit():
    tool = FullTextJournalSearchTool(
        include_offline_search=False,
        include_online_search=True,
        include_pubmed=True,
        include_eupmc=True,
        include_s2=True
    )
    
    # Use a broad query that returns many results
    query = "Disinfection Byproduct Formation"
    
    print(f"Running search for '{query}' with expectations of LIMIT applied...")
    
    # We expect the tool to fetch > 20 results raw, but only output 20 enriched
    results = tool._run(
        query=[query], 
        max_results=50 # Request MORE to test the cap
    )
    
    print(f"Final Result Count: {len(results)}")
    
    if len(results) <= 20:
        print("SUCCESS: Result count respected the safety limit of 20.")
    else:
        print(f"FAILURE: Result count {len(results)} exceeded the safety limit.")

if __name__ == "__main__":
    test_online_limit()
