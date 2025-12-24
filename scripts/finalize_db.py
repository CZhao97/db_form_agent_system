import lancedb
import time

DB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"
CLEAN_TABLE = "papers_index_clean"
FINAL_TABLE = "papers_index"
BACKUP_TABLE = "papers_index_old"

def finalize():
    print(f"Connecting to {DB_URI}...")
    db = lancedb.connect(DB_URI)
    
    if CLEAN_TABLE not in db.table_names():
        print(f"Error: {CLEAN_TABLE} does not exist. Run deduplicate_db.py first.")
        return

    # Verify clean table has data
    tbl_clean = db.open_table(CLEAN_TABLE)
    count = tbl_clean.count_rows()
    print(f"Clean table has {count} rows.")
    if count == 0:
        print("Error: Clean table is empty!")
        return

    # Rename old table to backup
    if FINAL_TABLE in db.table_names():
        print(f"Renaming {FINAL_TABLE} to {BACKUP_TABLE}...")
        try:
            db.rename_table(FINAL_TABLE, BACKUP_TABLE)
        except Exception as e:
            print(f"Warning: Could not rename {FINAL_TABLE} (maybe it doesn't exist?): {e}")
            # If rename fails, we might want to just drop the backup if it exists and try again?
            # Or maybe the table doesn't exist.
            pass

    # Rename clean table to final
    print(f"Renaming {CLEAN_TABLE} to {FINAL_TABLE}...")
    db.rename_table(CLEAN_TABLE, FINAL_TABLE)
    
    # Open the new final table
    tbl = db.open_table(FINAL_TABLE)
    
    # Create FTS Index
    print("Building FTS Index on new table... (This may take a while)")
    start_time = time.time()
    tbl.create_fts_index("text", replace=True)
    end_time = time.time()
    
    print(f"FTS Index built in {end_time - start_time:.2f} seconds.")
    print("Database finalization complete!")

if __name__ == "__main__":
    finalize()
