
import os
import json
import glob
import numpy as np

def calculate_reduction():
    files = glob.glob("**/*.ner_cache.json", recursive=True)
    
    total_mentions = 0
    total_unique = 0
    
    file_stats = []
    
    for f in files:
        try:
            with open(f, 'r') as fd:
                data = json.load(fd)
                
            # Handle different structures if any (based on previous 'merged_output' check)
            # Standard structure seems to be { "MESH:ID": { "mentions": [...] } }
            
            # If "merged_output" key exists, use it
            if "merged_output" in data:
                data = data["merged_output"]
                
             # Count unique entities (keys)
            unique_count = len(data.keys())
            
            # Count total mentions
            mentions_count = 0
            for key, val in data.items():
                if isinstance(val, dict) and "mentions" in val:
                    mentions_count += len(val["mentions"])
            
            if mentions_count > 0:
                reduction = (1 - (unique_count / mentions_count)) * 100
                file_stats.append(reduction)
                total_mentions += mentions_count
                total_unique += unique_count
                
        except Exception as e:
            continue
            
    avg_reduction = np.mean(file_stats) if file_stats else 0
    global_reduction = (1 - (total_unique / total_mentions)) * 100 if total_mentions > 0 else 0
    
    print(f"Files Processed: {len(file_stats)}")
    print(f"Total Mentions: {total_mentions}")
    print(f"Total Unique: {total_unique}")
    print(f"Global Reduction: {global_reduction:.2f}%")
    print(f"Average Per-File Reduction: {avg_reduction:.2f}%")

if __name__ == "__main__":
    calculate_reduction()
