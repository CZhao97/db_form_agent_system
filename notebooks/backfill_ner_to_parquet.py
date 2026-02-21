
import os
import sys
import json
import time
import argparse
import lancedb
import pandas as pd
import pyarrow as pa
from tqdm import tqdm
from pathlib import Path

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

def backfill_ner_to_parquet(limit: int = None, processing_batch_size: int = 64, dry_run: bool = False, output_dir: str = "backfill_results"):
    print(f"Connecting to LanceDB at {LANCEDB_URI}...")
    db = lancedb.connect(LANCEDB_URI)
    
    if TABLE_NAME not in db.table_names():
        print(f"Table {TABLE_NAME} not found!")
        return

    tbl = db.open_table(TABLE_NAME)
    total_rows = len(tbl)
    print(f"Table '{TABLE_NAME}' opened. Total rows: {total_rows}")

    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Use a scanner / iterator
    scan_batch_size = 10000
    
    processed_count = 0
    saved_count = 0
    buffer = []
    part_counter = 0
    save_interval = 1000 # Save every 1000 processed rows to a file
    
    print(f"Scanning table in batches of {scan_batch_size}...")
    print("Using Limit/Offset Pagination for safe streaming...")
    iterator = [] 
    
    # Calculate smart start/end offset based on sharding
    start_offset = 0
    end_offset = total_rows
    
    if args.num_shards > 1:
        # Partition the total rows
        chunk_size = total_rows // args.num_shards
        start_offset = args.shard_id * chunk_size
        # The last shard takes the remainder
        if args.shard_id == args.num_shards - 1:
            end_offset = total_rows
        else:
            end_offset = (args.shard_id + 1) * chunk_size
        print(f"Shard {args.shard_id}/{args.num_shards}: Processing range {start_offset} to {end_offset} (Size: {end_offset - start_offset})")
    elif args.offset is not None:
         start_offset = args.offset
    elif args.scan_tail:
         # Start 200k rows from end (safe buffer)
         start_offset = max(0, total_rows - 200000)
         print(f"Tail Scan Mode: Starting from offset {start_offset} (Total: {total_rows})")
    
    # We will construct a generator for the batches
    def batch_generator():
        current_offset = start_offset
        while True:
            # Check if we exceeded total rows or end of shard
            if current_offset >= end_offset:
                break
            
            # Adjust batch size for last chunk
            effective_limit = min(scan_batch_size, end_offset - current_offset)
                
            try:
                # Use search().limit().offset() to verify safe fetching
                arrow_batch = tbl.search().limit(effective_limit).offset(current_offset).to_arrow()
                if arrow_batch.num_rows == 0:
                    break
                    
                yield arrow_batch, current_offset
                current_offset += arrow_batch.num_rows
                
                # Safety break if we got fewer rows than requested (end of table)
                if arrow_batch.num_rows < effective_limit:
                    break
            except Exception as e:
                print(f"Pagination failed at offset {current_offset}: {e}")
                break
                
    iterator = batch_generator()
    
    for batch_arrow, batch_offset in iterator:
        if limit and processed_count >= limit:
            break
            
        df_batch = batch_arrow.to_pandas()
        
        # Filter Candidate Rows
        # Condition: ner_results is null, empty string, or "{}"
        mask_empty = (df_batch['ner_results'].isna()) | (df_batch['ner_results'] == "") | (df_batch['ner_results'] == "{}")
        candidates = df_batch[mask_empty].copy()
        
        if candidates.empty:
            current_scanned = batch_offset + (batch_arrow.num_rows if hasattr(batch_arrow, 'num_rows') else len(df_batch))
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
                        ner_gpu=args.gpu_id, # Use specific GPU
                        linker_gpu=args.gpu_id,
                        ner_mini_batch_size=len(sub_texts),
                        disable_linking=False
                    )
                except Exception as e:
                    print(f"Error in NER batch: {e}")
                    ner_results_list = [{} for _ in sub_texts]
            else:
                ner_results_list = [{"chemicals": ["DRY_RUN_CHEM"]}] * len(sub_texts)
                
            # Buffer Results
            for idx, (_, row) in enumerate(sub_batch.iterrows()):
                res = ner_results_list[idx]
                doc_id = row['doc_id']
                chunk_id = row['chunk_id']
                
                # Format
                if not res or "chemicals" not in res or not res["chemicals"]:
                    final_json = json.dumps({"chemicals": []})
                else:
                    final_json = json.dumps(res)
                
                buffer.append({
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "ner_results": final_json
                })
                
                processed_count += 1
            
            # Flush Buffer if needed
            if len(buffer) >= save_interval:
                save_buffer(buffer, output_dir, args.shard_id, part_counter)
                saved_count += len(buffer)
                part_counter += 1
                buffer = [] # Clear buffer
                
    # Final Flush
    if buffer:
        save_buffer(buffer, output_dir, args.shard_id, part_counter)
        saved_count += len(buffer)
        
    print(f"Backfill Complete. Processed {processed_count} rows. Saved {saved_count} rows to Parquet.")

def save_buffer(buffer, output_dir, shard_id, part_id):
    if not buffer: return
    df = pd.DataFrame(buffer)
    filename = f"ner_backfill_shard_{shard_id}_part_{part_id}.parquet"
    filepath = os.path.join(output_dir, filename)
    try:
        df.to_parquet(filepath, index=False)
        print(f"Saved {len(df)} rows to {filepath}")
    except Exception as e:
        print(f"Failed to save parquet {filepath}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill missing NER results in LanceDB safely.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of rows to process.")
    parser.add_argument("--batch_size", type=int, default=64, help="Batch size for NER model.")
    parser.add_argument("--dry_run", action="store_true", help="Run without saving changes.")
    parser.add_argument("--offset", type=int, default=None, help="Start scanning from this offset.")
    parser.add_argument("--scan_tail", action="store_true", help="Start from the end of the DB (last 200k rows) to find recent additions.")
    parser.add_argument("--shard_id", type=int, default=0, help="Shard ID (0-indexed).")
    parser.add_argument("--num_shards", type=int, default=1, help="Total number of shards.")
    parser.add_argument("--gpu_id", type=int, default=0, help="GPU ID to use.")
    parser.add_argument("--output_dir", type=str, default="backfill_results", help="Directory to save parquet files.")
    
    args = parser.parse_args()
    
    backfill_ner_to_parquet(limit=args.limit, processing_batch_size=args.batch_size, dry_run=args.dry_run, output_dir=args.output_dir)
