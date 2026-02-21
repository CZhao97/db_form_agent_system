
import os
import glob
import json
import logging
from collections import defaultdict

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

def load_ner_cache_simple(file_path):
    # Simplified loader that handles the variations we know about
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        if "merged_output" in data:
            return data["merged_output"]
        if "per_file_results" in data:
            merged = {}
            for f_entry in data["per_file_results"]:
                for k, v in f_entry.get("entities", {}).items():
                    if k not in merged:
                         merged[k] = {"synonyms": v.get("synonyms", []), "mentions": v.get("mentions", [])}
                    else:
                         merged[k]["mentions"].extend(v.get("mentions", []))
            return merged
        # Flat dict
        if isinstance(data, dict) and len(data) > 0:
            return data
        return {}
    except:
        return {}

def calculate_ablation_metrics():
    ablation_dir = "agent/searching_results/ablation_study"
    
    # 1. Recursive Find to mimic Stage 2 discovery
    files = glob.glob(os.path.join(ablation_dir, "**", "*.ner_cache.json"), recursive=True)
    log.info(f"Found {len(files)} cache files.")
    
    # 2. Group by Paper (Parent Directory)
    paper_map = defaultdict(list)
    for f in files:
        parent_dir = os.path.dirname(f)
        paper_map[parent_dir].append(f)
        
    log.info(f"Found {len(paper_map)} unique papers/sessions.")
    
    total_unique_entities = 0
    total_raw_mentions = 0
    
    # 3. Aggregate
    for paper_dir, cache_files in paper_map.items():
        # Merge entities for this paper
        paper_entities = set() # Set of unique IDs
        paper_mentions_count = 0
        
        for f in cache_files:
            data = load_ner_cache_simple(f)
            for k, val in data.items():
                paper_entities.add(k)
                if isinstance(val, dict) and "mentions" in val:
                    paper_mentions_count += len(val["mentions"])
        
        total_unique_entities += len(paper_entities)
        total_raw_mentions += paper_mentions_count
        
    print("-" * 30)
    print(f"Papers Processed: {len(paper_map)}")
    print(f"Total Unique NER Entities (Denominator): {total_unique_entities}")
    print(f"Total Raw Mentions: {total_raw_mentions}")
    if len(paper_map) > 0:
         print(f"Avg Unique per Paper: {total_unique_entities / len(paper_map):.1f}")
         reduction = (1 - (total_unique_entities / total_raw_mentions)) * 100 if total_raw_mentions else 0
         print(f"Stage 1 Reduction (NER Normalization): {reduction:.2f}%")

if __name__ == "__main__":
    calculate_ablation_metrics()
