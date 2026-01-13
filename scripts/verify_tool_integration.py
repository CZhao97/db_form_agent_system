import lancedb
import pandas as pd
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("test_integration")

DB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"

def test_offline_integration():
    print(f"Connecting to {DB_URI}...")
    db = lancedb.connect(DB_URI)
    if TABLE_NAME not in db.table_names():
        print("Table not found!")
        return

    tbl = db.open_table(TABLE_NAME)
    
    test_title = "Editorial: Pathogenomics of the Genus Brucella and Beyond"
    print(f"Testing search for title: '{test_title}'")

    try:
        # Use simple search (Vector) which uses the embedding model implicitly
        print("Attempting Vector Search (Safe)...")
        res = tbl.search(test_title).limit(1).to_pandas()
        
        if not res.empty:
            row = res.iloc[0]
            print("\n[SUCCESS] Document Found:")
            print(f"  Title: {row.get('title')}")
            print(f"  Doc ID: {row.get('doc_id')}")
            
            # Verify NER
            ner_res = row.get("ner_results")
            print(f"  NER Data Present? {'Yes' if ner_res else 'No'}")
            print(f"  NER Content Length: {len(str(ner_res))}")
            print(f"  NER Content (excerpt): {str(ner_res)[:200]}...") 
        else:
            print("[FAIL] No document found.")
            
    except Exception as e:
        print(f"[CRITICAL FAIL] Search logic threw error: {e}")

if __name__ == "__main__":
    test_offline_integration()
