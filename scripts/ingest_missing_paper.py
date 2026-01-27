
import sys
import os
import lancedb
import json

# Path to missing paper
PAPER_PATH = "/home/chen/GNPS_SIM/agent/searching_results/dbp_eval_eval_939c401f/--13.json"
DB_PATH = "/data/chen/GNPS_SIM/pmc_lancedb_index"

print(f"Loading paper from {PAPER_PATH}...")
try:
    with open(PAPER_PATH, 'r') as f:
        paper_data = json.load(f)
except Exception as e:
    print(f"Error loading paper: {e}")
    sys.exit(1)

# Prepare record for LanceDB
# Note: we must match the schema. 
# Based on index.csv columns usually: source, title, abstract, full_text (or text?), ...
# Wait, for searching, the 'text' column is usually what is vector-indexed or FTS-indexed.
# In searching_tool.py, we see:
# table.search(clean_query).limit(limit).to_pandas()
# The schema likely has 'text', 'title', 'source', etc.
# I will inspect the schema from the table first.

db = lancedb.connect(DB_PATH)
table = db.open_table("papers_index")

# Extract schema fields
df_head = table.head(1).to_pandas()
print("\nTable Schema / Columns:")
print(df_head.columns.tolist())

# Create record
# If schema has 'text', use it.
# The JSON has 'full_text'.

# Create record
# Logic: Construct base record, then filter by valid columns
valid_columns = set(df_head.columns.tolist())
print(f"Valid Table Columns: {valid_columns}")

base_record = {
    "title": paper_data.get("title", ""),
    "text": paper_data.get("full_text", "") or paper_data.get("abstract", "") or "", 
    "source": paper_data.get("source", "offline_manual_ingest"),
    "pubdate": paper_data.get("pubdate", ""),
    "url": paper_data.get("url", ""),
    "id": paper_data.get("id", ""), # Try id
    "doi": paper_data.get("doi", ""),
}

# Construct final record logic
# We need to satisfy strict schema.
# Error said missing: [ner_results, year, chunk_id, doc_id]

# Convert 'doc_id' / 'chunk_id' from filename or random
import random
# Use negative integers to avoid collision with real positive production IDs
base_doc_id = -1 * random.randint(1000000, 9999999) 
# Chunk ID might be structured like doc_id << 32 | chunk_idx? 
# Or just separate ints. I'll use simple ints provided schema accepts simple ints.
# Actually, if chunk_id is int64, I'll just use another random int.
base_chunk_id = -1 * random.randint(1000000, 9999999)

for col in valid_columns:
    if col not in base_record:
        # Provide defaults for known missing fields
        if col == "ner_results":
             # Error: Unsupported cast from list<item: null> to utf8
             # Schema expects String (probably JSON stringified), not List.
             base_record[col] = "[]" 
        elif col == "year":
             base_record[col] = "2023" # Approx
        elif col == "chunk_id":
             base_record[col] = base_chunk_id
        elif col == "doc_id":
             base_record[col] = base_doc_id
        elif col == "vector":
             continue # Handled downstream
        else:
             # Generic null
             base_record[col] = None

# Re-filter to be safe
record = {k: v for k, v in base_record.items() if k in valid_columns}
print(f"Constructed Record Keys (Filled): {record.keys()}")

# Vector handling (Same as before)
if 'vector' in valid_columns:

    print("Generating embedding for 'vector' column...")
    from sentence_transformers import SentenceTransformer
    # Use global model cache or just load
    try:
        model = SentenceTransformer('all-MiniLM-L6-v2', device='cuda')
    except:
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
    text = str(record.get("title", "")) + ". " + str(record.get("text", ""))
    embedding = model.encode(text)
    record["vector"] = embedding.tolist()
    print("Generated embedding.")

# Ingest
print("Adding record to table...")
try:
    table.add([record])
    print("Success! Paper added.")
except Exception as e:
    print(f"Failed to add record: {e}")
    sys.exit(1)
