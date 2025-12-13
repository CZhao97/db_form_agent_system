import os
import glob
import lancedb
import json
import shutil
import sys
import time
import argparse
from typing import List, Dict, Any
from tqdm import tqdm

# Add current directory to sys.path to ensure imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from lancedb.pydantic import LanceModel, Vector
from lancedb.embeddings import get_registry
from lancedb.rerankers import RRFReranker
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --- Configuration ---
# Use absolute path for DB to avoid confusion
LANCEDB_URI = os.path.abspath("./pmc_lancedb_index")
TABLE_NAME = "papers_index"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Use the path where the user seems to have data
INPUT_DIR = "/data/chen/pubmed_corpus/pmc_extracted_text"
# MAX_FILES = 1000 # Removed global limit, controlled by argument
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
# BATCH_SIZE removed here, will be an argument

# Ensure clean start
# if os.path.exists(LANCEDB_URI):
#     print(f"Removing existing database at {LANCEDB_URI}...")
#     shutil.rmtree(LANCEDB_URI)

# --- 1. Initialize Components ---
# print("Initializing embedding model...")
registry = get_registry()
# Explicitly use CUDA for embeddings to speed up DB insertion
# Note: This assumes the script is run with access to a GPU.
try:
    func = registry.get("huggingface").create(name=EMBEDDING_MODEL_NAME, device="cuda")
except Exception as e:
    print(f"Warning: Could not load embedding model on CUDA: {e}. Falling back to CPU.")
    func = registry.get("huggingface").create(name=EMBEDDING_MODEL_NAME)

class PaperChunk(LanceModel):
    text: str = func.SourceField()
    vector: Vector(func.ndims()) = func.VectorField()
    doc_id: str
    title: str
    year: str
    source: str
    chunk_id: int
    ner_results: str # JSON string containing NER entities

# print(f"Connecting to LanceDB at {LANCEDB_URI}...")
# db = lancedb.connect(LANCEDB_URI)
reranker = RRFReranker()

# Text Splitter for full document indexing
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    length_function=len,
)

def build_database(limit: int = None, shard_id: int = 0, num_shards: int = 1, gpu_id: int = 0, file_batch_size: int = 1000, ner_batch_size: int = 256, linker_batch_size: int = 1024):
    # Import here to avoid circular dependency
    try:
        from chemical_ner_tool import extract_chemicals_with_nen_batch, _filter_relevant_sections
    except ImportError:
        code_dir = os.path.join(os.getcwd(), 'code')
        if os.path.exists(code_dir) and code_dir not in sys.path:
            sys.path.append(code_dir)
        from chemical_ner_tool import extract_chemicals_with_nen_batch, _filter_relevant_sections

    # Only remove if we are starting fresh and not just appending/resuming
    # For this script, we'll assume overwrite if limit is small (test), or append if full run?
    # Let's stick to overwrite for now to be safe, or handle existing DB gracefully.
    if limit and limit < 10000 and os.path.exists(LANCEDB_URI) and shard_id == 0 and num_shards == 1:
         print(f"Removing existing database at {LANCEDB_URI} for test run...")
         shutil.rmtree(LANCEDB_URI)

    print(f"Connecting to LanceDB at {LANCEDB_URI}...")
    db = lancedb.connect(LANCEDB_URI)
    
    # Create table if not exists, else open it
    if TABLE_NAME in db.table_names():
        tbl = db.open_table(TABLE_NAME)
    else:
        tbl = db.create_table(TABLE_NAME, schema=PaperChunk, mode="overwrite")

    # --- 2. Data Preparation ---
    current_input_dir = INPUT_DIR
    print(f"Scanning {current_input_dir} for text files...")
    if not os.path.exists(current_input_dir):
        print(f"Error: Input directory {current_input_dir} does not exist.")
        current_input_dir = "./pmc_extracted_text"
        print(f"Trying local directory: {current_input_dir}")

    # Use iglob for iterator if possible, but we need sort/slice for deterministic behavior
    # For 6M files, glob might be slow.
    # Let's try to listdir and filter manually or just use glob if it's fast enough.
    # glob.glob returns a list, which consumes memory for 6M strings (approx 600MB-1GB RAM). Acceptable.
    txt_files = glob.glob(os.path.join(current_input_dir, "*.txt"))
    txt_files.sort()

    if not txt_files:
        print(f"No text files found in {current_input_dir}!")
        return

    total_files = len(txt_files)
    
    # Sharding Logic
    if num_shards > 1:
        shard_size = total_files // num_shards
        start_idx = shard_id * shard_size
        end_idx = start_idx + shard_size if shard_id < num_shards - 1 else total_files
        files_to_process = txt_files[start_idx:end_idx]
        print(f"Processing Shard {shard_id+1}/{num_shards} (Files {start_idx} to {end_idx})...")
    else:
        files_to_process = txt_files

    if limit:
        files_to_process = files_to_process[:limit]
    
    print(f"Processing {len(files_to_process)} files (Total available: {total_files})...")
    
    # --- Resume Logic ---
    checkpoint_dir = "checkpoints"
    os.makedirs(checkpoint_dir, exist_ok=True)
    checkpoint_path = os.path.join(checkpoint_dir, f"shard_{shard_id}_progress.txt")
    
    start_offset = 0
    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, "r") as f:
                start_offset = int(f.read().strip())
            print(f"Found checkpoint. Resuming Shard {shard_id} from file index {start_offset}...")
        except Exception as e:
            print(f"Error reading checkpoint: {e}. Starting from 0.")

    start_time = time.time()
    processed_count = start_offset # Correct processed count for estimation
    
    # Process in batches
    for i in range(start_offset, len(files_to_process), file_batch_size):
        t_batch_start = time.time()
        batch_files = files_to_process[i : i + file_batch_size]
        batch_contents = []
        batch_metadata = []
        
        # 1. Read Batch
        t_read_start = time.time()
        for fpath in batch_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                
                lines = content.split('\n')
                title = "Unknown Title"
                year = "Unknown Year"
                
                # Simple metadata extraction
                for line in lines[:10]:
                    if line.startswith("Title: "):
                        title = line.replace("Title: ", "").strip()
                    elif line.startswith("Year: "):
                        year = line.replace("Year: ", "").strip()
                
                doc_id = os.path.basename(fpath)
                
                batch_contents.append(content)
                batch_metadata.append({
                    "doc_id": doc_id,
                    "title": title,
                    "year": year,
                    "source": "PMC"
                })
            except Exception as e:
                print(f"Error reading {fpath}: {e}")
                continue
        t_read_end = time.time()

        if not batch_contents:
            continue

        # 2. Run NER on Batch
        t_ner_start = time.time()
        try:
            # Increase batch sizes for better GPU utilization
            # Re-enable linking as requested, but with larger batches and compilation
            ner_results_list = extract_chemicals_with_nen_batch(
                batch_contents, 
                verbose=True, # Enable verbose to see internal timing
                ner_gpu=gpu_id,             # Use specified GPU
                linker_gpu=gpu_id,          # Use specified GPU
                ner_mini_batch_size=ner_batch_size,    # Argument controlled
                linker_mini_batch_size=linker_batch_size, # Argument controlled
                disable_linking=False       # Re-enabled
            )
        except Exception as e:
            print(f"Error in NER batch: {e}")
            ner_results_list = [{}] * len(batch_contents) # Fallback
        t_ner_end = time.time()

        # 3. Chunk and Prepare for Indexing
        t_prep_start = time.time()
        data_to_index = []
        for idx, content in enumerate(batch_contents):
            meta = batch_metadata[idx]
            ner_res = ner_results_list[idx] if idx < len(ner_results_list) else {}
            ner_json = json.dumps(ner_res)
            
            # Apply filtering logic for stored text as well
            # If 'Results' or 'Discussion' exists, use only that for indexing.
            # Otherwise use full text.
            filtered_content = _filter_relevant_sections(content)
            
            chunks = text_splitter.split_text(filtered_content)
            for chunk_id, chunk_text in enumerate(chunks):
                contextualized_text = f"Title: {meta['title']}. {chunk_text}"
                data_to_index.append({
                    "text": contextualized_text,
                    "doc_id": meta['doc_id'],
                    "title": meta['title'],
                    "year": meta['year'],
                    "source": meta['source'],
                    "chunk_id": chunk_id,
                    "ner_results": ner_json
                })
        t_prep_end = time.time()

        # 4. Add to LanceDB
        t_db_start = time.time()
        if data_to_index:
            tbl.add(data_to_index)
        t_db_end = time.time()
        
        # Update Checkpoint
        next_start = i + len(batch_files)
        with open(checkpoint_path, "w") as f:
            f.write(str(next_start))
        
        processed_count += len(batch_files)
        
        # 5. Progress and Estimation
        elapsed = time.time() - start_time
        avg_time_per_file = elapsed / processed_count
        remaining_files = len(files_to_process) - processed_count
        est_remaining = remaining_files * avg_time_per_file
        
        # Detailed timing for this batch
        t_read = t_read_end - t_read_start
        t_ner = t_ner_end - t_ner_start
        t_prep = t_prep_end - t_prep_start
        t_db = t_db_end - t_db_start
        t_total_batch = time.time() - t_batch_start
        
        print(f"Batch {i//file_batch_size + 1}: {len(batch_files)} files. Total: {t_total_batch:.2f}s")
        print(f"  Read: {t_read:.2f}s, NER+Link: {t_ner:.2f}s, Prep: {t_prep:.2f}s, DB: {t_db:.2f}s")
        print(f"Processed {processed_count}/{len(files_to_process)} files. "
              f"Avg: {avg_time_per_file:.2f}s/file. "
              f"Est remaining: {est_remaining/60:.1f} min. "
              f"Total Est (for {total_files} files): {(total_files * avg_time_per_file)/3600:.1f} hours")

    # Create FTS Index at the end
    print("Building FTS Index...")
    tbl.create_fts_index("text", replace=True)
    print("Indexing complete.")

# --- 4. Search Demo ---
def search_papers(query):
    print(f"\n--- Running Hybrid Search for: '{query}' ---")
    
    db = lancedb.connect(LANCEDB_URI)
    if TABLE_NAME not in db.table_names():
        print(f"Table {TABLE_NAME} not found.")
        return

    tbl = db.open_table(TABLE_NAME)
    
    results = (
        tbl.search(query, query_type="hybrid")
        .rerank(reranker)
        .limit(3)
        .to_pandas()
    )
    
    if results.empty:
        print("No results found.")
        return

    for _, row in results.iterrows():
        doc_id = row['doc_id']
        score = row['_relevance_score']
        title = row['title']
        chunk_text = row['text']
        ner_res = row['ner_results']
        
        print(f"\nRANK (Score: {score:.4f})")
        print(f"  ID: {doc_id}")
        print(f"  Title: {title}")
        print(f"  Match: {chunk_text[:300]}...")
        print(f"  NER Results (preview): {ner_res[:200]}...")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build offline LanceDB from PMC text files.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of files to process (for testing).")
    parser.add_argument("--shard_id", type=int, default=0, help="Shard ID (0-indexed) for parallel processing.")
    parser.add_argument("--num_shards", type=int, default=1, help="Total number of shards.")
    parser.add_argument("--gpu_id", type=int, default=0, help="GPU ID to use (relative to visible devices).")
    parser.add_argument("--file_batch_size", type=int, default=2000, help="Number of files to read per batch.")
    parser.add_argument("--ner_batch_size", type=int, default=320, help="Mini-batch size for NER model.")
    parser.add_argument("--linker_batch_size", type=int, default=2048, help="Mini-batch size for Linker model.")
    
    args = parser.parse_args()
    
    build_database(
        limit=args.limit, 
        shard_id=args.shard_id, 
        num_shards=args.num_shards,
        gpu_id=args.gpu_id,
        file_batch_size=args.file_batch_size,
        ner_batch_size=args.ner_batch_size,
        linker_batch_size=args.linker_batch_size
    )
    
    # Only run search demo if we are running the first shard or a small test
    if args.shard_id == 0 and (args.limit is not None and args.limit < 1000):
        search_papers("chronic pain stress")
        search_papers("brucellosis")
