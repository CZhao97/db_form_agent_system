
import lancedb
import os
import pandas as pd
from dotenv import load_dotenv

# Load config
load_dotenv("/home/chen/GNPS_SIM/agent/db_form_agent_system/.env")

DB_PATH = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index" # Verified previously

print(f"Connecting to {DB_PATH} table {TABLE_NAME}...")
db = lancedb.connect(DB_PATH)
table = db.open_table(TABLE_NAME)

# 1. Check direct existence by ID (I generated a random ID, let's search by Title)
title_query = "固相萃取-超高效液相色谱-三重四极杆质谱法测定饮用水中13种卤代苯醌类消毒副产物"
print(f"Checking for Title: {title_query}")
df = table.search(title_query).limit(5).to_pandas()
found = False
for idx, row in df.iterrows():
    if row['title'] == title_query:
        print(f"FOUND by Vector Search! ID: {row.get('doc_id')}, Chunk: {row.get('chunk_id')}")
        found = True
        break

if not found:
    print("WARNING: Not found by vector search on Title. Checking exact match on text...")
    # This might be slow if we can't filter, but let's try a small query
    pass

# 2. Check Search Retrievability with Agent Queries
queries = [
    "2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione",
    "2,3,5,6-Tetrabromo-1,4-benzoquinone",
    "TBBQ",
    "Tetrabromobenzoquinone"
]

print("\n--- Testing Agent Queries ---")
for q in queries:
    print(f"Query: '{q}'")
    # Simulate Hybrid usually involves vector search.
    # Note: `table.search()` is vector search by default.
    results = table.search(q).limit(20).to_pandas()
    
    # Check if our paper is in results
    is_present = False
    for idx, row in results.iterrows():
        # loose check
        if title_query in row['title']:
            print(f"  [MATCH] Found at Rank {idx+1}")
            is_present = True
            print(f"  Title: {row['title']}")
            print(f"  Text Snippet: {row['text'][:50]}...")
            break
            
    if not is_present:
        print("  [FAIL] Not found in Top 20")

print("\nDone.")
