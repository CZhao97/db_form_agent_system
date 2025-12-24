import lancedb
import pandas as pd
import os

LANCEDB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"

def get_existing_doc_ids():
    print(f"Connecting to {LANCEDB_URI}...")
    db = lancedb.connect(LANCEDB_URI)
    tbl = db.open_table(TABLE_NAME)
    
    print("Fetching existing doc_ids...")
    # to_arrow() failed with byte array overflow (too much data).
    # We should iterate in batches and only select the doc_id column.
    
    unique_ids = set()
    total_rows = 0
    
    # Use search() to create a query, select columns, and iterate
    # limit(None) means all results.
    query = tbl.search().limit(None).select(["doc_id"])
    
    # Iterate over batches
    for batch in query.to_batches():
        ids = batch["doc_id"].to_pylist()
        unique_ids.update(ids)
        total_rows += len(ids)
        if total_rows % 1000000 == 0:
            print(f"Processed {total_rows} rows...")
            
    print(f"Total rows: {total_rows}")
    print(f"Unique doc_ids: {len(unique_ids)}")
    
    return unique_ids

if __name__ == "__main__":
    ids = get_existing_doc_ids()
    # Save to a file so the build script can load it quickly
    with open("existing_doc_ids.txt", "w") as f:
        for doc_id in ids:
            f.write(doc_id + "\n")
    print("Saved existing_doc_ids.txt")
