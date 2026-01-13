import lancedb
import time
import os

DB_PATH = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"

def create_index():
    print(f"Connecting to LanceDB at {DB_PATH}...")
    try:
        db = lancedb.connect(DB_PATH)
    except Exception as e:
        print(f"Failed to connect to DB: {e}")
        return

    print(f"Opening table '{TABLE_NAME}'...")
    try:
        tbl = db.open_table(TABLE_NAME)
    except Exception as e:
        print(f"Failed to open table: {e}")
        return
    
    print(f"Table opened. Row count (approx): {tbl.count_rows()}")
    
    print("Starting FTS index creation on column 'text'.")
    print("This operation puts a Tantivy inverted index on the column.")
    print("Please wait...")
    
    t0 = time.time()
    try:
        # replace=True ensures we overwrite any existing index or partial state
        tbl.create_fts_index("text", replace=True)
    except Exception as e:
        print(f"CRITICAL ERROR during index creation: {e}")
        print("Ensure 'tantivy' is installed (pip install tantivy) if required by this LanceDB version.")
        return
        
    t1 = time.time()
    duration = t1 - t0
    print(f"SUCCESS: FTS index created in {duration:.2f} seconds.")

if __name__ == "__main__":
    create_index()
