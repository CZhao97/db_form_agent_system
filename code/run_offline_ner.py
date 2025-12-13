import os
import json
import glob
from chemical_ner_tool import extract_chemicals_with_nen_batch, merge_batch_results

# Configuration
INPUT_DIR = "./pmc_extracted_text"
OUTPUT_FILE = "./ner_results.json"
BATCH_SIZE = 10 # Number of documents to process in one batch

def main():
    # 1. Get list of text files
    txt_files = glob.glob(os.path.join(INPUT_DIR, "*.txt"))
    print(f"Found {len(txt_files)} text files in {INPUT_DIR}")
    
    if not txt_files:
        print("No text files found. Exiting.")
        return

    # For demonstration, let's process a subset (e.g., first 20 files)
    # Remove the slice [:20] to process all files
    files_to_process = txt_files[:20] 
    print(f"Processing {len(files_to_process)} files...")

    all_results = []
    
    # 2. Process in batches
    for i in range(0, len(files_to_process), BATCH_SIZE):
        batch_files = files_to_process[i : i + BATCH_SIZE]
        batch_texts = []
        
        print(f"Reading batch {i // BATCH_SIZE + 1}...")
        for fpath in batch_files:
            with open(fpath, "r", encoding="utf-8") as f:
                batch_texts.append(f.read())
        
        print(f"Running NER on batch of {len(batch_texts)} documents...")
        try:
            # Run the NER tool's batch function
            batch_results = extract_chemicals_with_nen_batch(
                batch_texts,
                ner_gpu=0,
                linker_gpu=0, # Use same GPU if only 1 available, or 0 and 1
                use_fp16=True,
                verbose=True
            )
            
            # The result is a list of dicts (one per document)
            # We can attach the filename to the result for reference if needed
            for doc_idx, res in enumerate(batch_results):
                # res is { "MESH:D000...": { "mentions": [...] }, ... }
                # We might want to structure it by file
                filename = os.path.basename(batch_files[doc_idx])
                all_results.append({
                    "file": filename,
                    "entities": res
                })
                
        except Exception as e:
            print(f"Error processing batch: {e}")

    # 3. Save results
    print(f"Saving results to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    
    print("Done.")

if __name__ == "__main__":
    main()
