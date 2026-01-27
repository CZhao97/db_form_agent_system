
import sys
import os
import lancedb
import pandas as pd

# Path to DB
db = lancedb.connect("/data/chen/GNPS_SIM/pmc_lancedb_index")
table = db.open_table("papers_index")

pd.set_option('display.max_colwidth', None)

print("\nSearching for '13 halogenated benzoquinone'...")
results = table.search("13 halogenated benzoquinone", query_type="fts").limit(5).to_pandas()
if len(results) == 0:
    print("No results found.")
else:
    for i, row in results.iterrows():
        print(f"\n--- Result {i+1} ---")
        print(f"Title: {row.get('title')}")
        print(f"Text Snippet: {row.get('text', '')[:200]}")

print("\nSearching for 'TBBQ'...")
results = table.search("TBBQ", query_type="fts").limit(5).to_pandas()
if len(results) == 0:
    print("No results found.")
else:
    for i, row in results.iterrows():
        print(f"\n--- Result {i+1} ---")
        print(f"Title: {row.get('title')}")
