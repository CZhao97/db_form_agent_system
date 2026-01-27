
import os
import sys
import json
import time
import argparse
import lancedb
import pandas as pd
import pyarrow as pa
from tqdm import tqdm

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.append(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Try imports
try:
    from code.chemical_ner_tool import extract_chemicals_with_nen_batch
    from code.build_offline_db import TABLE_NAME, LANCEDB_URI
except ImportError:
    sys.path.append(os.path.join(parent_dir, 'code'))
    from chemical_ner_tool import extract_chemicals_with_nen_batch
    from build_offline_db import TABLE_NAME, LANCEDB_URI

def backfill_ner(limit: int = None, processing_batch_size: int = 64, dry_run: bool = False):
    print(f"Connecting to LanceDB at {LANCEDB_URI}...")
    db = lancedb.connect(LANCEDB_URI)
    
    if TABLE_NAME not in db.table_names():
        print(f"Table {TABLE_NAME} not found!")
        return

    tbl = db.open_table(TABLE_NAME)
    total_rows = len(tbl)
    print(f"Table '{TABLE_NAME}' opened. Total rows: {total_rows}")

    # Use a scanner / iterator to handle large datasets
    # Stream in chunks of 10k to check for candidates
    scan_batch_size = 10000
    
    # We can try to filter at the scanner level if possible, but string check is fragile.
    # We'll stream and filter in python.
    
    processed_count = 0
    updated_count = 0
    
    print(f"Scanning table in batches of {scan_batch_size}...")
    
    # Using iter_batches for efficient scanning
    # Note: We need a way to identifying rows to update. 
    # Ensure we select 'doc_id', 'chunk_id', 'ner_results' and 'text'
    
    # Fix: LanceTable may not have to_batches directly. 
    # Use to_arrow() which returns a pyarrow Table (zero-copy usually) and then iterate batches.
    # CAUTION: If to_arrow() loads everything, this will fail.
    # Determine safe method.
    # Optimized Pagination Loop (Fallback for missing pylance)
    print("Using Limit/Offset Pagination for safe streaming...")
    iterator = [] 
    
    # Calculate smart start offset if not provided
    # If we assume we only care about recent additions, we can start near the end.
    start_offset = 0
    if args.offset is not None:
         start_offset = args.offset
    elif args.scan_tail:
         # Start 200k rows from end (safe buffer)
         start_offset = max(0, total_rows - 200000)
         print(f"Tail Scan Mode: Starting from offset {start_offset} (Total: {total_rows})")
    
    # We will construct a generator for the batches
    def batch_generator():
        current_offset = start_offset
        while True:
            # Check if we exceeded total rows 
            if current_offset >= total_rows:
                break
                
            try:
                # Use search().limit().offset() to verify safe fetching
                arrow_batch = tbl.search().limit(scan_batch_size).offset(current_offset).to_arrow()
                if arrow_batch.num_rows == 0:
                    break
                    
                yield arrow_batch
                current_offset += arrow_batch.num_rows
                
                # Safety break
                if arrow_batch.num_rows < scan_batch_size:
                    break
            except Exception as e:
                print(f"Pagination failed at offset {current_offset}: {e}")
                break
                
    iterator = batch_generator()
    
    for batch_arrow in iterator:
        if limit and processed_count >= limit:
            break
            
        df_batch = batch_arrow.to_pandas()
        
        # Filter Candidate Rows
        # Condition: ner_results is null, empty string, or "{}"
        mask_empty = (df_batch['ner_results'].isna()) | (df_batch['ner_results'] == "") | (df_batch['ner_results'] == "{}")
        candidates = df_batch[mask_empty].copy()
        
        if candidates.empty:
            current_scanned = current_offset + (batch_arrow.num_rows if hasattr(batch_arrow, 'num_rows') else len(df_batch))
            # Rough estimate of progress
            if (current_scanned // scan_batch_size) % 50 == 0:
               print(f"[Heartbeat] Scanned ~{current_scanned} rows... (No missing NER found yet)")
            continue
            
        # Limit handling within batch
        if limit and (processed_count + len(candidates) > limit):
            candidates = candidates.head(limit - processed_count)
        
        print(f"Found {len(candidates)} candidates in current scan batch.")
        
        # Process candidates in smaller sub-batches (processing_batch_size)
        texts_to_process = candidates['text'].tolist()
        
        # Process in chunks
        for i in range(0, len(candidates), processing_batch_size):
            sub_batch = candidates.iloc[i : i + processing_batch_size]
            sub_texts = sub_batch['text'].tolist()
            
            ner_results_list = []
            if not dry_run:
                try:
                    ner_results_list = extract_chemicals_with_nen_batch(
                        sub_texts, 
                        verbose=False,
                        ner_gpu=0,
                        linker_gpu=0,
                        ner_mini_batch_size=len(sub_texts),
                        disable_linking=False
                    )
                except Exception as e:
                    print(f"Error in NER batch: {e}")
                    ner_results_list = [{} for _ in sub_texts]
            else:
                ner_results_list = [{"chemicals": ["DRY_RUN_CHEM"]}] * len(sub_texts)
                
            # Perform Updates
            # Updating row-by-row or batch-update?
            # tbl.update(where=..., values=...) 
            # Constructing a large WHERE clause is inefficient. 
            # We will try to loop updates. This is slow but safe for now.
            # Optimization: If many updates, maybe create a new partial table and merge? 
            # For now, let's just do individual updates as the number of "Missing NER" rows is likely small compared to total DB.
            
            for idx, (_, row) in enumerate(sub_batch.iterrows()):
                res = ner_results_list[idx]
                doc_id = row['doc_id']
                chunk_id = row['chunk_id']
                
                # Format
                if not res or "chemicals" not in res or not res["chemicals"]:
                    final_json = json.dumps({"chemicals": []})
                else:
                    final_json = json.dumps(res)
                
                if not dry_run:
                    # Update specific row
                    # Double quotes for SQL string literals
                    # Using parameter substitution if possible, but LanceDB python string SQL is standard.
                    where_clause = f"doc_id = '{doc_id}' AND chunk_id = {chunk_id}"
                    try:
                        tbl.update(where=where_clause, values={"ner_results": final_json})
                        updated_count += 1
                    except Exception as e:
                        print(f"Failed to update {doc_id} chunk {chunk_id}: {e}")
                else:
                    updated_count += 1
                    
            if not dry_run and updated_count % 10 == 0:
                print(f"Updated {updated_count} rows so far...")
                
        processed_count += len(candidates)
        
    print(f"Backfill Complete. Processed {processed_count} rows. Updated {updated_count} rows.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill missing NER results in LanceDB safely.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of rows to process.")
    parser.add_argument("--batch_size", type=int, default=32, help="Batch size for NER model.")
    parser.add_argument("--dry_run", action="store_true", help="Run without saving changes.")
    parser.add_argument("--offset", type=int, default=None, help="Start scanning from this offset.")
    parser.add_argument("--scan_tail", action="store_true", help="Start from the end of the DB (last 200k rows) to find recent additions.")
    
    args = parser.parse_args()
    
    backfill_ner(limit=args.limit, processing_batch_size=args.batch_size, dry_run=args.dry_run)
