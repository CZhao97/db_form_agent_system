import lancedb
import time

DB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"

def main():
    print(f"Connecting to {DB_URI}...")
    db = lancedb.connect(DB_URI)
    
    # 1. Check for clean table
    if "papers_index_clean" not in db.table_names():
        # Fallback: Check if user already renamed it manually
        if "papers_index" in db.table_names():
             print("'papers_index_clean' not found, but 'papers_index' exists.")
             print("Assuming table swap already happened. Proceeding to index check.")
             tbl = db.open_table("papers_index")
        else:
            print("Error: Neither 'papers_index_clean' nor 'papers_index' found!")
            return
    else:
        # 2. Rename / Swap
        if "papers_index" in db.table_names():
            print("Removing old 'papers_index' table...")
            db.drop_table("papers_index")
        
        print("Renaming 'papers_index_clean' to 'papers_index' using filesystem...")
        # db.rename_table("papers_index_clean", "papers_index") # Not supported in OSS
        import os
        src = os.path.join(DB_URI, "papers_index_clean.lance")
        dst = os.path.join(DB_URI, "papers_index.lance")
        if os.path.exists(src):
            if os.path.exists(dst):
                 import shutil
                 shutil.rmtree(dst)
            os.rename(src, dst)
        else:
             print(f"Warning: {src} not found. checking if {dst} exists...")
             if not os.path.exists(dst):
                 print("Error: Neither table found.")
                 return

        tbl = db.open_table("papers_index")
    
    # 3. Build FTS Index
    print(f"Table ready with {tbl.count_rows()} rows.")
    
    print("--- Starting FTS Index Build ---")
    start_time = time.time()
    
    try:
        tbl.create_fts_index("text", replace=True)
    except Exception as e:
        print(f"Index build error: {e}")
        raise e
        
    end_time = time.time()
    print(f"FTS Index created successfully in {(end_time - start_time)/60:.2f} minutes.")
    print("Done.")

if __name__ == "__main__":
    main()
