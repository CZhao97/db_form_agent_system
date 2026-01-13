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
NER_SCRIPT_PATH = "code/build_offline_db.py"

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
        log(f"Resuming rescue from offset {current_offset}...")

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
        # Use 'doc_id' which stores the filename
        df_iter = dest_tbl.search().select(["doc_id"]).limit(None).to_pandas()
        db_files = set(df_iter["doc_id"].tolist())
    except Exception as e:
        log(f"Error fetching file list: {e}")
        return []

    log(f"DB contains {len(db_files)} unique files.")

    # 2. Scan disk and find missing
    log(f"Scanning source directory: {SOURCE_TEXT_DIR}")
    missing_files = []
    scanned_count = 0
    
    try:
        with os.scandir(SOURCE_TEXT_DIR) as it:
            for entry in it:
                if entry.name.endswith('.txt') and entry.is_file():
                    scanned_count += 1
                    if entry.name not in db_files:
                        missing_files.append(entry.name)
                    
                    if scanned_count % 100000 == 0:
                        print(f"Scanned {scanned_count} files... Found {len(missing_files)} missing so far.", end='\r')
                        sys.stdout.flush()
    except Exception as e:
        log(f"Error scanning directory: {e}")

    print("") # Newline after progress
    log(f"Total scanned: {scanned_count}. Found {len(missing_files)} missing files that need re-computation.")
    
    return missing_files

def step_3_recompute_parallel(missing_files):
    """
    Sets up a temp directory with missing files and runs the build script in parallel.
    """
    log("--- STEP 3: RECOMPUTE MISSING DATA (PARALLEL) ---")
    
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

    # 2. Determine Sharding
    num_files = len(missing_files)
    # Heuristic: at least 100 files per shard, max 2 shards (Reduced for stability)
    num_shards = max(1, min(2, num_files // 100))
    
    log(f"Launching {num_shards} parallel shards for recomputation...")
    
    # Set PyTorch Env Var
    env = os.environ.copy()
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    
    processes = []
    for i in range(num_shards):
        real_gpu_id = i % 2 # Alternate between GPU 0 and 1
        
        # We set CUDA_VISIBLE_DEVICES so that 'cuda' always maps to the desired GPU
        # and the script sees it as 'device 0'.
        shard_env = env.copy()
        shard_env["CUDA_VISIBLE_DEVICES"] = str(real_gpu_id)
        
        cmd = [
            sys.executable, NER_SCRIPT_PATH,
            "--input_dir", TEMP_RECOMPUTE_DIR,
            "--table_name", RESCUED_TABLE,
            "--shard_id", str(i),
            "--num_shards", str(num_shards),
            "--gpu_id", "0", # Since we mask with CUDA_VISIBLE_DEVICES, the script should use 0
            "--file_batch_size", "50",   # Reduced for stability
            "--ner_batch_size", "32",    # Reduced for stability
            "--linker_batch_size", "8",  # Reduced for stability
            "--skip_index"               # Prevent redundant indexing (Hang fix)
        ]
        
        log(f"Launching Shard {i} on GPU {real_gpu_id}...")
        p = subprocess.Popen(cmd, env=shard_env)
        processes.append(p)
    
    # Wait for completion
    for i, p in enumerate(processes):
        p.wait()
        if p.returncode != 0:
            log(f"Shard {i} failed with exit code {p.returncode}")
            # We don't exit immediately, let others finish, but this is an error state
    
    log("Recomputation complete.")

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
        step_3_recompute_parallel(missing_files)
    else:
        log("No data was missing.")

    log("Recovery Workflow Complete.")
    log(f"Your clean data is in table: '{RESCUED_TABLE}'")
    log("Step 4 (FTS Indexing) has been removed from this script to prevent hangs.")
    log("Please run 'scripts/finalize_recovery.py' to swap tables and build the index efficiently.")

if __name__ == "__main__":
    main()
