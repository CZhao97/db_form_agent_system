import lancedb
import time
import os

DB_PATH = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"

def build_index():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database path {DB_PATH} not found.")
        return

    print(f"Connecting to {DB_PATH}...")
    db = lancedb.connect(DB_PATH)
    
    if TABLE_NAME not in db.table_names():
        print(f"Error: Table {TABLE_NAME} does not exist.")
        return

    tbl = db.open_table(TABLE_NAME)
    print(f"Table opened. Rows: {tbl.count_rows()}")

    print("Starting Index Creation (IVF-PQ)...")
    print("Configuration: Metric=cosine, Partitions=1024, SubVectors=48")
    
    start = time.time()
    # 384 dims (MiniLM). 48 subvectors => 8 dims per code (good compression)
    # 1024 partitions => Good for ~1M+ rows
    tbl.create_index(
        metric="cosine", 
        vector_column_name="vector", 
        num_partitions=1024, 
        num_sub_vectors=48,
        replace=True
    )
    end = time.time()
    
    print(f"Index built successfully in {end - start:.2f} seconds.")

if __name__ == "__main__":
    build_index()
