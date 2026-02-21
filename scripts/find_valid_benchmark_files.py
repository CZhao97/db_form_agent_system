
import os
import json
import glob

SEARCH_DIR = "agent/searching_results/e2e_run_20260125_130247/literature_searching"

def main():
    files = glob.glob(os.path.join(SEARCH_DIR, "*.json"))
    valid_candidates = []

    print(f"Scanning {len(files)} files...")
    for f in files:
        if "ner_cache" in f: continue
        
        cache_path = f.replace(".json", ".ner_cache.json")
        if not os.path.exists(cache_path):
            continue
            
        try:
            with open(f, 'r') as fd:
                data = json.load(fd)
                text = data.get("full_text", "")
                if text and len(str(text)) > 10000:
                    valid_candidates.append((f, len(str(text))))
        except:
            pass
            
    # Sort by size descending
    valid_candidates.sort(key=lambda x: x[1], reverse=True)
    
    print(f"Found {len(valid_candidates)} valid candidates (Full Text > 10k + NER Cache).")
    for f, size in valid_candidates[:10]:
        print(f"{os.path.basename(f)} | Size: {size}")

if __name__ == "__main__":
    main()
