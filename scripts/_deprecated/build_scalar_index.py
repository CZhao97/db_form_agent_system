
import lancedb
import time

DB_PATH = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"

def main():
    print(f"Connecting to {DB_PATH}...")
    db = lancedb.connect(DB_PATH)
    
    if TABLE_NAME not in db.table_names():
        print(f"Table {TABLE_NAME} not found!")
        return

    table = db.open_table(TABLE_NAME)
    print(f"Table opened. Rows: {table.count_rows()}")
    
    print("Creating SCALAR index on 'doc_id'...")
    start = time.time()
    # Create scalar index for exact match lookups
    # Note: LanceDB might support this via create_index or standard lance behavior
    # For newer LanceDB: create_scalar_index("doc_id")
    # If not available, we rely on the fact that filtering on a column is generally fast if sorted or standard parquet optimization,
    # but explicit index is better.
    try:
        table.create_scalar_index("doc_id", replace=True)
    except Exception as e:
        print(f"Method create_scalar_index failed: {e}")
        print("Trying legacy create_index with scalar type (if applicable)...")
        # Fallback or different API version check
        # Usually checking documentation... 
        # But let's assume create_scalar_index is the way for recent versions.
        raise e
        
    print(f"Index built in {time.time() - start:.2f} seconds.")
    print("Verification: Performing test query...")
    
    # Test query
    t0 = time.time()
    # A dummy ID to test speed
    res = table.search().where("doc_id = '36827767'").limit(1).to_pandas()
    print(f"Query took {time.time() - t0:.4f}s. Result empty? {res.empty}")

if __name__ == "__main__":
    main()
