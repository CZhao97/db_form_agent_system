
import glob
import json
import os

def calc_funnel_stats():
    base_dir = "agent/searching_results/ablation_study/Baseline"
    
    # 1. Count Total Unique Entities (NER Stage)
    ner_files = glob.glob(os.path.join(base_dir, "**", "*.ner_cache.json"), recursive=True)
    total_unique_ner = 0
    
    print(f"Found {len(ner_files)} NER cache files.")
    
    for f in ner_files:
        try:
            with open(f, 'r') as fd:
                data = json.load(fd)
            
            # Handle possible structures
            if "merged_output" in data:
                total_unique_ner += len(data["merged_output"])
            elif "per_file_results" in data:
                 # If no merged output, sum unique from per_file (deduplication required?)
                 # Assuming per_file_results logic mimics the notebook
                 temp_set = set()
                 for pfr in data["per_file_results"]:
                     for key in pfr.get("entities", {}):
                         temp_set.add(key)
                 total_unique_ner += len(temp_set)
            else:
                # Standard dict structure { "MESH:ID": ... }
                total_unique_ner += len(data)
                
        except Exception:
            pass
            
    # 2. Count Total Downstream Sessions (Verification Stage)
    # Downstream folders usually start with "downstream_" or "dbp_eval_eval_" 
    # In the baseline listing, they were named "dbp_eval_eval_XXXX"
    
    # We need to distinguish between 'search session' (parent) and 'downstream session' (child)
    # But the listing showed "dbp_eval_eval_..." as immediate children of Baseline?
    # Let me check the directory structure again. 
    # The logs showed "Using session directory: .../dbp_eval_eval_dde159cf"
    # This might be the PARENT session for a batch or a Single Downstream session?
    
    # Actually, the listing showed 623 directories in `Baseline`.
    # And `ablation_full_restore_12.log` mentions "Saved 15 papers from this chunk".
    # So `dbp_eval_eval_...` might be the "Upper Stream" session (one per batch/paper search?).
    # And inside it, there should be "downstream_..." folders?
    
    # Let's count directories that contain "state.json" AND have "downstream" in their path or are leaf notes?
    # Better: Count global "state.json" files, but exclude the top-level ones if any.
    # The downstream sessions have a specific structure.
    
    # Let's assume the 623 folders ARE the downstream sessions (or upper stream sessions?).
    # If they are Upper Stream sessions, they contain the NER cache.
    # If they are Downstream sessions, they contain the verification trace.
    
    # Let's check ONE directory content to be sure.
    pass

if __name__ == "__main__":
    calc_funnel_stats()
