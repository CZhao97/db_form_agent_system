
import sys
import os
import json
import logging
import re
import pathlib

# Add code/ to path
sys.path.append(os.path.join(os.getcwd(), 'code'))

from searching_tool import FullTextJournalSearchTool

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

DB_PATH = "/data/chen/GNPS_SIM/pmc_lancedb_index"

def parse_run_dir(output_str):
    # Output format: "Total Papers Found: N. Run_dir: /path/to/dir"
    match = re.search(r"Run_dir:\s*(.+)$", output_str)
    if match:
        return match.group(1).strip()
    return None

def test_online_only():
    print("\n" + "="*50)
    print("TEST A: ONLINE ONLY SEARCH (4-Bromophenol)")
    print("="*50)
    
    # Disable offline
    tool = FullTextJournalSearchTool(
        include_offline_search=False,
        offline_index_path=DB_PATH,
        include_pubmed=True,
        include_eupmc=True,
        include_s2=False, # Faster
        include_preprints=False
    )
    
    query = "4-Bromophenol disinfection byproduct"
    print(f"Querying: '{query}'")
    
    try:
        output_str = tool._run(query, max_results=5)
        print(f"Tool Output: {output_str}")
        
        run_dir = parse_run_dir(output_str)
        if not run_dir:
            print("ERROR: Could not parse Run_dir from output.")
            return

        results_file = os.path.join(run_dir, "index.ndjson")
        if not os.path.exists(results_file):
             print(f"ERROR: index.ndjson not found in {run_dir}")
             return
             
        results = []
        with open(results_file, 'r') as f:
            for line in f:
                if line.strip():
                    results.append(json.loads(line))

        print(f"\nFound {len(results)} results in results.json")
        sources = {}
        for r in results:
            s = r.get('source', 'Unknown')
            sources[s] = sources.get(s, 0) + 1
            print(f"- [{s}] {r.get('title', '')[:80]}...")
            
        print("\nSource Breakdown:", sources)
        
        if len(results) > 0 and "offline_db" not in sources:
            print("SUCCESS: Online Search returned results and Offline was excluded.")
        else:
            print("WARNING: unexpected results (offline_db found or no results).")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_offline_only():
    print("\n" + "="*50)
    print("TEST B: OFFLINE ONLY SEARCH (4-Bromophenol)")
    print("="*50)
    
    # Enable offline, Disable online sources
    tool = FullTextJournalSearchTool(
        include_offline_search=True,
        offline_index_path=DB_PATH,
        include_pubmed=False,
        include_eupmc=False,
        include_s2=False,
        include_preprints=False
    )
    
    query = "4-Bromophenol" 
    print(f"Querying: '{query}'")
    
    try:
        output_str = tool._run(query, max_results=5)
        print(f"Tool Output: {output_str}")
        
        run_dir = parse_run_dir(output_str)
        if not run_dir:
            print("ERROR: Could not parse Run_dir from output.")
            return

        
        # Check for index.ndjson
        results_file = os.path.join(run_dir, "index.ndjson")
        if not os.path.exists(results_file):
             print(f"ERROR: index.ndjson not found in {run_dir}")
             return

        results = []
        with open(results_file, 'r') as f:
            for line in f:
                if line.strip():
                    results.append(json.loads(line))
        
        print(f"\nFound {len(results)} results in index.ndjson.")
        sources = {}
        found_clean_text = False
        for r in results:
            s = r.get('source', 'Unknown')
            sources[s] = sources.get(s, 0) + 1
            
            # Check for title prefix artifact (should be gone now)
            title = r.get('title', '')
            text = r.get('full_text', '')
            text_sample = text[:50]
            
            print(f"- [{s}] Title: {title[:60]}... | Text Start: '{text_sample}'")
            
            # Verification: Text should NOT start with "Title: {title}"
            expected_prefix = f"Title: {title}"
            if text.startswith(expected_prefix):
                print(f"  FAIL: Title still present in text!")
            else:
                 found_clean_text = True

        print("\nSource Breakdown:", sources)
        
        if "offline_db" in sources and sources["offline_db"] > 0:
            if found_clean_text:
                print("SUCCESS: Offline DB returned CLEAN results.")
            else:
                print("PARTIAL SUCCESS: Offline DB returned results but cleaning verify unclear.")
        else:
            print("FAILURE: Offline DB returned nothing.")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_online_only()
    test_offline_only()
