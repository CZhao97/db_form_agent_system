
import sys
import os
import json
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

# Add code dir
sys.path.append(os.path.abspath("code"))

try:
    from chemical_ner_tool import extract_chemicals_with_nen_batch
except ImportError as e:
    log.error(f"Failed to import chemical_ner_tool: {e}")
    sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_local_ner_wrapper.py <file1> <file2> ...")
        sys.exit(1)
        
    filepaths = sys.argv[1:]
    texts = []
    for fp in filepaths:
        with open(fp, "r", encoding="utf-8") as f:
            t = f.read()
            texts.append(t)
            log.info(f"Loaded {os.path.basename(fp)}: {len(t)} chars")
            
    sys.stderr.write(f"Running NER on {len(texts)} texts...\n")
    
    # Run NER
    try:
        results = extract_chemicals_with_nen_batch(
            texts, 
            ner_gpu=0, 
            linker_gpu=0,
            use_fp16=True,
            disable_linking=False, # Try enabling linking
            verbose=True
        )
    except Exception as e:
        sys.stderr.write(f"NER Extraction Failed: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    sys.stderr.write(f"NER finished. Got {len(results)} results.\n")
    
    # Convert results to list of sets (serialized as list of lists)
    output = []
    for doc_result in results:
        unique_chems = set()
        for kb_id, details in doc_result.items():
            if kb_id.startswith("TEXT:"):
                for m in details.get("mentions", []):
                    # Basic normalization
                    clean_m = m.split(" (Context:")[0].strip().lower().rstrip("s").rstrip("es")
                    unique_chems.add(clean_m)
            else:
                unique_chems.add(kb_id)
        output.append(list(unique_chems))
    
    # Dump JSON to file
    with open("ner_output.json", "w", encoding="utf-8") as f:
        json.dump(output, f)
    log.info("Wrote ner_output.json")

if __name__ == "__main__":
    main()
