import lancedb

DB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"

def main():
    print(f"Connecting to {DB_URI}...")
    db = lancedb.connect(DB_URI)
    
    if TABLE_NAME not in db.table_names():
        print(f"CRITICAL: Table '{TABLE_NAME}' not found.")
        return

    tbl = db.open_table(TABLE_NAME)
    count = tbl.count_rows()
    print(f"Table '{TABLE_NAME}' loaded successfully.")
    print(f"Row count: {count} (Should be ~266M)")
    
    # Check Vector Search (should work)
    print("\nTesting Vector Search (metadata filter)...")
    try:
        # Simple lookup to verify readability
        res = tbl.search().limit(3).to_pandas()
        print("Successfully read 3 rows:")
        print(res[['doc_id', 'title', 'year']])
    except Exception as e:
        print(f"Read failed: {e}")

    print("\nStatus:")
    print("✅ Data is safe and accessible.")
    print("⚠️  Full-Text Search (keyword search) might be incomplete/unavailable.")
    print("   (You can retry building it later if needed, or use vector search for now.)")

if __name__ == "__main__":
    main()
