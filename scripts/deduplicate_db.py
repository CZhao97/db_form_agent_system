import lancedb
import pyarrow as pa
import time
import os
import sys

# Configuration
DB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"

SOURCE_TABLE = "papers_index"
DEST_TABLE = "papers_index_clean"
BATCH_BUFFER_SIZE = 100000   # Accumulate 100k rows before writing (reduced from 1M to save RAM)
MAX_BATCH_SIZE = 1000        # Start with 1000, adaptively reduce on error
MIN_BATCH_SIZE = 1           # Minimum batch size
SKIP_LOG = "deduplicate_skipped.log"

def deduplicate():
    print(f"Connecting to {DB_URI}...")
    sys.stdout.flush()
    db = lancedb.connect(DB_URI)
    
    if SOURCE_TABLE not in db.table_names():
        print(f"Source table {SOURCE_TABLE} does not exist!")
        return

    tbl = db.open_table(SOURCE_TABLE)
    print(f"Opened source table: {SOURCE_TABLE}")
    sys.stdout.flush()
    
    # Check if dest exists
    if DEST_TABLE in db.table_names():
        print(f"Destination table {DEST_TABLE} already exists. Deleting it...")
        db.drop_table(DEST_TABLE)

    seen_keys = set()
    total_rows = 0
    kept_rows = 0
    start_time = time.time()

    print(f"Starting deduplication process...")
    print(f"Reading batches (starting batch_size={MAX_BATCH_SIZE})...")
    sys.stdout.flush()

    new_tbl = None
    buffer = []
    buffer_size = 0

    try:
        # Adaptive batching: process the table in row ranges
        total_rows_in_table = tbl.count_rows()
        row_idx = 0
        batch_idx = 0
        while row_idx < total_rows_in_table:
            batch_size = MAX_BATCH_SIZE
            while batch_size >= MIN_BATCH_SIZE:
                try:
                    batch = tbl.search().limit(None).offset(row_idx).limit(batch_size).to_batches(batch_size=batch_size)
                    batch = next(batch)
                    # batch is a pyarrow.RecordBatch
                    doc_ids = batch["doc_id"].to_pylist()
                    chunk_ids = batch["chunk_id"].to_pylist()
                    indices_to_keep = []
                    for i, (doc_id, chunk_id) in enumerate(zip(doc_ids, chunk_ids)):
                        key = (doc_id, chunk_id)
                        if key not in seen_keys:
                            seen_keys.add(key)
                            indices_to_keep.append(i)
                    if not indices_to_keep:
                        total_rows += len(batch)
                        row_idx += len(batch)
                        break
                    indices_array = pa.array(indices_to_keep)
                    unique_batch = batch.take(indices_array)
                    buffer.append(unique_batch)
                    buffer_size += len(unique_batch)
                    total_rows += len(batch)
                    kept_rows += len(unique_batch)
                    if buffer_size >= BATCH_BUFFER_SIZE:
                        print(f"Flushing {buffer_size} rows to DB...")
                        sys.stdout.flush()
                        if new_tbl is None:
                            new_tbl = db.create_table(DEST_TABLE, data=pa.Table.from_batches(buffer))
                        else:
                            new_tbl.add(pa.Table.from_batches(buffer))
                        buffer = []
                        buffer_size = 0
                    if total_rows % 1000000 == 0:
                        elapsed = time.time() - start_time
                        print(f"Processed {total_rows} rows... Kept {kept_rows} unique. ({total_rows/elapsed:.2f} rows/s)")
                        sys.stdout.flush()
                    row_idx += len(batch)
                    break  # Success, move to next batch
                except Exception as batch_err:
                    if batch_size == 1:
                        # Log and skip this row
                        with open(SKIP_LOG, "a") as skiplog:
                            skiplog.write(f"Row {row_idx} failed: {batch_err}\n")
                            try:
                                batch = tbl.search().limit(None).offset(row_idx).limit(1).to_batches(batch_size=1)
                                batch = next(batch)
                                doc_id = batch["doc_id"].to_pylist()[0]
                                chunk_id = batch["chunk_id"].to_pylist()[0]
                                skiplog.write(f"  doc_id={doc_id}, chunk_id={chunk_id}\n")
                            except Exception:
                                skiplog.write("  (Could not extract doc_id)\n")
                        print(f"Skipped row {row_idx} due to error: {batch_err}")
                        sys.stdout.flush()
                        total_rows += 1
                        row_idx += 1
                        break
                    else:
                        batch_size = batch_size // 2
                        if batch_size < MIN_BATCH_SIZE:
                            batch_size = MIN_BATCH_SIZE
        # Flush remaining buffer
        if buffer:
            print(f"Flushing remaining {buffer_size} rows to DB...")
            sys.stdout.flush()
            if new_tbl is None:
                new_tbl = db.create_table(DEST_TABLE, data=pa.Table.from_batches(buffer))
            else:
                new_tbl.add(pa.Table.from_batches(buffer))
    except Exception as e:
        print(f"An error occurred during processing: {e}")
        import traceback
        traceback.print_exc()
        print("Attempting to save progress...")
    
    end_time = time.time()
    print("-" * 30)
    print(f"Deduplication complete (or stopped).")
    print(f"Total processed rows: {total_rows}")
    print(f"Total unique rows kept: {kept_rows}")
    print(f"Duplicates removed: {total_rows - kept_rows}")
    print(f"Time taken: {end_time - start_time:.2f} seconds")
    print("-" * 30)
    print(f"Clean data is in table: '{DEST_TABLE}'")
    print("Verify the new table before deleting the old one!")

if __name__ == "__main__":
    deduplicate()
