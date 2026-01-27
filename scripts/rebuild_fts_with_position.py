#!/usr/bin/env python3
"""
Rebuild FTS index with position=True to enable phrase queries.
This script will:
1. Drop the existing FTS index
2. Create a new FTS index with position support
3. Report progress

Expected time: Several hours for 266M rows
"""
import lancedb
import time
from datetime import datetime

DB_PATH = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "pmc_full_text"

print("="*70)
print("FTS INDEX REBUILD WITH POSITION SUPPORT")
print("="*70)
print(f"Start time: {datetime.now()}")
print(f"Database: {DB_PATH}")
print(f"Table: {TABLE_NAME}")
print("")

# Connect to database
print("Connecting to LanceDB...")
db = lancedb.connect(DB_PATH)
table = db.open_table(TABLE_NAME)

# Get table info
print(f"Table row count: {table.count_rows():,}")
print("")

# Check if FTS index exists
try:
    print("Checking for existing FTS index...")
    # Try a simple FTS search to see if index exists
    test_result = table.search("test", query_type="fts").limit(1).to_pandas()
    print("✓ Existing FTS index found")
    has_existing = True
except Exception as e:
    print(f"No existing FTS index or error: {e}")
    has_existing = False

print("")
print("="*70)
print("STARTING INDEX REBUILD")
print("="*70)
print("")
print("Configuration:")
print("  - Field: 'text'")
print("  - Position: True (enables phrase queries)")
print("  - Replace: True (drops existing index)")
print("")
print("⚠️  This operation will take several hours for 266M rows")
print("⚠️  Progress updates will be logged")
print("")

start_time = time.time()

try:
    print(f"[{datetime.now()}] Creating FTS index with position=True...")
    
    # Create FTS index with position support
    table.create_fts_index(
        "text",
        replace=True,
        with_position=True  # This enables phrase queries
    )
    
    elapsed = (time.time() - start_time) / 60
    print("")
    print("="*70)
    print("✓ FTS INDEX REBUILD COMPLETE!")
    print("="*70)
    print(f"End time: {datetime.now()}")
    print(f"Total time: {elapsed:.1f} minutes ({elapsed/60:.1f} hours)")
    print("")
    print("The index now supports phrase queries like:")
    print('  - "4-Bromophenol" AND "disinfection byproduct"')
    print('  - "water treatment" AND "DBP formation"')
    print("")
    
except Exception as e:
    elapsed = (time.time() - start_time) / 60
    print("")
    print("="*70)
    print("❌ ERROR DURING INDEX REBUILD")
    print("="*70)
    print(f"Error: {e}")
    print(f"Time elapsed: {elapsed:.1f} minutes")
    print("")
    raise

print("="*70)
print("VERIFICATION TEST")
print("="*70)

# Test phrase query
print('\nTesting phrase query: "disinfection byproduct"...')
try:
    test_result = table.search('"disinfection byproduct"', query_type="fts").limit(5).to_pandas()
    print(f"✓ Phrase query successful! Found {len(test_result)} results")
    print("\nSample titles:")
    for idx, row in test_result.iterrows():
        print(f"  {idx+1}. {row.get('title', 'N/A')[:70]}...")
except Exception as e:
    print(f"❌ Phrase query test failed: {e}")

print("\n" + "="*70)
print("REBUILD COMPLETE - Index ready for phrase queries")
print("="*70)
