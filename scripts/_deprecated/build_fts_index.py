import lancedb
import time

DB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"

def main():
    print(f"Connecting to {DB_URI}...")
    db = lancedb.connect(DB_URI)
    
    if TABLE_NAME not in db.table_names():
        print(f"Error: Table '{TABLE_NAME}' not found.")
        return

    tbl = db.open_table(TABLE_NAME)
    print(f"Table loaded. Rows: {tbl.count_rows()}")
    
    print("--- Starting FTS Index Build (Optimized) ---")
    print("Config: writer_heap_size=8GB, replace=True")
    
    start_time = time.time()
    try:
        # Increase heap size to 8GB to reduce flush frequency
        tbl.create_fts_index(
            "text", 
            replace=True, 
            writer_heap_size=8 * 1024 * 1024 * 1024
        )
    except Exception as e:
        print(f"Index build failed: {e}")
        raise e
        
    end_time = time.time()
    print(f"FTS Index created successfully in {(end_time - start_time)/60:.2f} minutes.")

if __name__ == "__main__":
    main()
