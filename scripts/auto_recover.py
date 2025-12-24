import lancedb
import pyarrow as pa
import os
import sys
import glob
import time
import shutil
import subprocess
import json
import pandas as pd
from pathlib import Path

# ================= CONFIGURATION =================
# Paths
DB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"
SOURCE_TABLE = "papers_index"
RESCUED_TABLE = "papers_index_clean"
SOURCE_TEXT_DIR = "/data/chen/pubmed_corpus/pmc_extracted_text"
TEMP_RECOMPUTE_DIR = "/data/chen/temp_recompute_batch"
RECOMPUTE_OUTPUT_DIR = "/data/chen/temp_recompute_results"

# Scripts
NER_SCRIPT_PATH = "code/build_offline_db.py"  # Path relative to where you run this script

# Tuning
BATCH_SIZE = 10000
# =================================================

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

def step_1_rescue_data(db):
    """
    Reads the corrupted table, skips bad blocks, and writes to a new clean table.
    Returns a set of filenames present in the CLEAN table.
    """
    log("--- STEP 1: RESCUE DATA ---")
    
    if SOURCE_TABLE not in db.table_names():
        log(f"Error: Source table {SOURCE_TABLE} not found.")
        sys.exit(1)

    tbl = db.open_table(SOURCE_TABLE)
    total_rows = tbl.count_rows()
    
    # Check if we can resume or start fresh
    if RESCUED_TABLE in db.table_names():
        log(f"Rescued table {RESCUED_TABLE} already exists. Opening...")
        dest_tbl = db.open_table(RESCUED_TABLE)
    else:
        dest_tbl = None

    current_offset = 0
    if dest_tbl:
        current_offset = dest_tbl.count_rows()
        log(f"Resuming rescue from row {current_offset}...")

    rescued_count = 0
    skipped_count = 0

    while current_offset < total_rows:
        try:
            # Attempt to read a batch
            batch = tbl.search().limit(BATCH_SIZE).offset(current_offset).to_arrow()
            
            if dest_tbl is None:
                dest_tbl = db.create_table(RESCUED_TABLE, data=batch)
            else:
                dest_tbl.add(batch)
            
            rescued_count += len(batch)
            current_offset += len(batch)
            
            if current_offset % 100000 == 0:
                log(f"Processed {current_offset}/{total_rows} rows...")

        except Exception as e:
            log(f"!!! CORRUPTION DETECTED at offset {current_offset} !!!")
            log(f"Error: {str(e)}")
            log(f"Performing HARD SKIP of {BATCH_SIZE} rows to bypass corrupted block.")
            
            # Skip the bad batch
            current_offset += BATCH_SIZE
            skipped_count += BATCH_SIZE
            
            # Re-connect to ensure DB state is clean after panic
            db = lancedb.connect(DB_URI)
            tbl = db.open_table(SOURCE_TABLE)
            if dest_tbl:
                dest_tbl = db.open_table(RESCUED_TABLE)
                
            log(f"Resuming at offset {current_offset}...")

    log(f"Rescue complete. Rescued: {rescued_count}, Lost/Skipped: {skipped_count}")
    return dest_tbl

def step_2_find_missing(dest_tbl):
    """
    Compares files in the clean DB vs files on disk.
    """
    log("--- STEP 2: IDENTIFY MISSING FILES ---")
    
    # 1. Get files currently in DB
    log("Fetching file list from clean DB...")
    # Assumes column name is 'file' or 'filename'. Adjust if needed.
    # We fetch in chunks to avoid OOM if the list is huge
    db_files = set()
    try:
        # Try 'file' first
        df_iter = dest_tbl.search().select(["file"]).limit(None).to_pandas()
        db_files = set(df_iter["file"].tolist())
    except:
        # Try 'filename' fallback
        log("Column 'file' not found, trying 'filename'...")
        df_iter = dest_tbl.search().select(["filename"]).limit(None).to_pandas()
        db_files = set(df_iter["filename"].tolist())

    log(f"DB contains {len(db_files)} unique files.")

    # 2. Get files on disk
    log(f"Scanning source directory: {SOURCE_TEXT_DIR}")
    disk_files = set(os.path.basename(f) for f in glob.glob(os.path.join(SOURCE_TEXT_DIR, "*.txt")))
    log(f"Disk contains {len(disk_files)} files.")

    # 3. Diff
    missing_files = list(disk_files - db_files)
    log(f"Found {len(missing_files)} missing files that need re-computation.")
    
    return missing_files

def step_3_recompute(missing_files):
    """
    Sets up a temp directory with missing files and runs the NER script.
    """
    log("--- STEP 3: RECOMPUTE MISSING DATA ---")
    
    if not missing_files:
        log("No files missing. Skipping recompute.")
        return

    # 1. Prepare Temp Directory
    if os.path.exists(TEMP_RECOMPUTE_DIR):
        shutil.rmtree(TEMP_RECOMPUTE_DIR)
    os.makedirs(TEMP_RECOMPUTE_DIR)
    
    log(f"Staging {len(missing_files)} files to {TEMP_RECOMPUTE_DIR}...")
    for fname in missing_files:
        src = os.path.join(SOURCE_TEXT_DIR, fname)
        dst = os.path.join(TEMP_RECOMPUTE_DIR, fname)
        if os.path.exists(src):
            os.symlink(src, dst) # Symlink is faster than copy
        else:
            log(f"Warning: Source file {src} not found!")

    # 2. Run the NER Builder Script
    # We call the user's existing script but point it to the temp dir
    cmd = [
        sys.executable, NER_SCRIPT_PATH,
        "--input_dir", TEMP_RECOMPUTE_DIR,
        "--db_uri", DB_URI,
        "--table_name", RESCUED_TABLE,
        "--shard_id", "0",
        "--num_shards", "1",
        "--gpu_id", "0", # Uses GPU 0 by default
        "--file_batch_size", "100"
    ]
    
    log(f"Launching NER script: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        log("Re-computation finished successfully.")
    except subprocess.CalledProcessError as e:
        log(f"NER script failed with error code {e.returncode}")
        sys.exit(1)

def step_4_merge_results(db):
    """
    Reads JSON outputs from step 3 and inserts them into the LanceDB table.
    """
    log("--- STEP 4: MERGE RESULTS ---")
    log("Step 4 is now handled directly by the recompute step (build_offline_db.py).")
    return

def main():
    log("Starting Auto-Recovery...")
    
    # Connection
    db = lancedb.connect(DB_URI)
    
    # 1. Rescue
    dest_tbl = step_1_rescue_data(db)
    
    # 2. Identify Missing
    missing_files = step_2_find_missing(dest_tbl)
    
    # 3. Recompute
    if missing_files:
        step_3_recompute(missing_files)
        
        # 4. Merge (Placeholder logic - requires schema knowledge)
        # If your NER script produces JSONs, you likely need to run your INGESTER on `RECOMPUTE_OUTPUT_DIR`.
        log("Recompute complete. Data should be in table.")
    else:
        log("No data was missing. Proceeding to indexing.")
        step_4_merge_results(db) # Mainly for indexing if no missing files

    log("Recovery Workflow Complete.")
    log(f"Your clean data is in table: '{RESCUED_TABLE}'")
    log("Verify it, then delete the old table and rename the new one.")

if __name__ == "__main__":
    main()