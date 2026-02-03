import os
import sys
import csv
import random
import json
import subprocess
from datetime import datetime

# Paths
# Assumes this script is in <PROJECT_ROOT>/scripts/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "evaluation_results_full_fresh_k10.csv")
OUTPUT_CSV = os.path.join(BASE_DIR, "offline_evaluation_sample.csv")

import argparse

def create_driver_script(compounds, env_vars, mode):
    driver_code = f"""
import sys
import os
import json
import time
import re
from langchain_community.callbacks import get_openai_callback

# Set env vars for this specific run
for k, v in {json.dumps(env_vars)}.items():
    os.environ[k] = v

# Paths
sys.path.insert(0, os.path.join('{BASE_DIR}', 'notebooks'))
sys.path.insert(0, '{BASE_DIR}')

try:
    from evaluate_dbp_downstream_only import evaluate_compound
except ImportError:
    # Fallback if running from a different cwd
    sys.path.append(os.getcwd())
    try:
        from evaluate_dbp_downstream_only import evaluate_compound
    except ImportError:
        print("ERROR: Could not import evaluate_dbp_downstream_only")
        sys.exit(1)

compounds = {json.dumps(compounds)}
prefix = "{mode}" # 'offline' or 'hybrid'
results_map = {{}}
temp_file = f'temp_{{prefix}}_results.json'

# Load existing if any (for resume capability)
if os.path.exists(temp_file):
    try:
        with open(temp_file, 'r') as f:
            results_map = json.load(f)
    except:
        pass

print(f"Processing {{len(compounds)}} compounds for mode: {{prefix}}...")

for i, compound in enumerate(compounds):
    if compound in results_map:
        print(f"[{{i+1}}/{{len(compounds)}}] Skipping already done: {{compound}}")
        continue

    print(f"[{{i+1}}/{{len(compounds)}}] Running ({{prefix}}): {{compound}}")
    try:
        start_time = time.time()
        with get_openai_callback() as cb:
            result = evaluate_compound(compound)
        end_time = time.time()
        duration = end_time - start_time
        
        # Extract fields we want
        verdict = result.get('agent_verdict', 'Error')
        norm_pred = result.get('normalized_prediction', 'Error')
        
        # Parse coverage info
        papers_analyzed = getattr(result, 'papers_analyzed', 0) # Fallback if not dict
        relevant_chunks = 0
        
        try:
            # Check if result dict has these (modified evaluate_compound usually passes them if structured)
            # Or parse from verdict string if evaluate_compound didn't give them directly
            if isinstance(result, dict):
                 papers_analyzed = result.get('papers_analyzed', 0)
                 relevant_chunks = result.get('relevant_chunks', 0)

            # If 0, try parsing string JSON blob (backup)
            if papers_analyzed == 0 and isinstance(verdict, str) and "{{" in verdict:
                start = verdict.find("{{")
                end = verdict.rfind("}}") + 1
                if start >= 0:
                    data = json.loads(verdict[start:end])
                    if "coverage" in data:
                        papers_analyzed = data["coverage"].get("papers_analyzed", 0)
                        relevant_chunks = data["coverage"].get("relevant_chunks", 0)
        except:
             pass

        results_map[compound] = {{
            f'{{prefix}}_agent_verdict': verdict,
            f'{{prefix}}_normalized_prediction': norm_pred,
            f'{{prefix}}_tokens': cb.total_tokens,
            f'{{prefix}}_cost': cb.total_cost,
            f'{{prefix}}_duration_seconds': round(duration, 2),
            f'{{prefix}}_papers_analyzed': papers_analyzed, 
            f'{{prefix}}_relevant_chunks': relevant_chunks
        }}
    except Exception as e:
        print(f"Error on {{compound}}: {{e}}")
        results_map[compound] = {{
            f'{{prefix}}_agent_verdict': 'Error',
            f'{{prefix}}_normalized_prediction': 'Error',
            f'{{prefix}}_tokens': 0,
            f'{{prefix}}_cost': 0.0,
            f'{{prefix}}_duration_seconds': 0.0,
            f'{{prefix}}_papers_analyzed': 0,
            f'{{prefix}}_relevant_chunks': 0,
            'error': str(e)
        }}
    
    # Incremental save
    with open(temp_file, 'w') as f:
        json.dump(results_map, f, indent=2)

"""
    with open("temp_driver_offline.py", "w") as f:
        f.write(driver_code)
    return "temp_driver_offline.py"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50, help="Number of compounds to sample/run")
    args = parser.parse_args()

    # 1. Read CSV
    if not os.path.exists(CSV_PATH):
        print(f"Error: CSV file not found at {CSV_PATH}")
        sys.exit(1)
        
    print(f"Reading {CSV_PATH}...")
    with open(CSV_PATH, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # 2. Sample
    random.seed(42) # Fixed seed for reproducibility
    if len(rows) > args.limit:
        sample_rows = random.sample(rows, args.limit)
    else:
        sample_rows = rows
    
    print(f"Sampled {len(sample_rows)} compounds (Limit: {args.limit}).")
    
    compounds = [r['IUPAC name'] for r in sample_rows]
    
    # 3. Define Environments
    env_offline = {
        "INCLUDE_OFFLINE_SEARCH": "True",
        "INCLUDE_ONLINE_SEARCH": "False",
        "LANGCHAIN_PROJECT": "DBP_Compar_Offline",
        "LANGCHAIN_TRACING_V2": "false"
    }
    
    env_hybrid = {
        "INCLUDE_OFFLINE_SEARCH": "True",
        "INCLUDE_ONLINE_SEARCH": "True",
        "LANGCHAIN_PROJECT": "DBP_Compar_Hybrid",
        "LANGCHAIN_TRACING_V2": "false"
    }

    # 4. Run Offline Pass
    print("\n=== STARTING OFFLINE PASS ===")
    script_offline = create_driver_script(compounds, env_offline, "offline")
    try:
        subprocess.run([sys.executable, script_offline], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error in offline pass: {e}")
        # Continue to hybrid anyway? Probably better to stop if offline fails hard
        # But for resilience we might continue.
    
    # 5. Run Hybrid Pass
    print("\n=== STARTING HYBRID PASS ===")
    script_hybrid = create_driver_script(compounds, env_hybrid, "hybrid")
    try:
        subprocess.run([sys.executable, script_hybrid], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error in hybrid pass: {e}")

    # 6. Read and Merge Results
    results_offline = {}
    if os.path.exists('temp_offline_results.json'):
         with open('temp_offline_results.json', 'r') as f:
             results_offline = json.load(f)

    results_hybrid = {}
    if os.path.exists('temp_hybrid_results.json'):
         with open('temp_hybrid_results.json', 'r') as f:
             results_hybrid = json.load(f)
             
    # 7. Write Combined CSV
    OUTPUT_COMPARISON_CSV = os.path.join(BASE_DIR, "comparison_results_offline_vs_hybrid.csv")
    
    # Define columns
    base_cols = list(sample_rows[0].keys())
    offline_cols = [
        'offline_agent_verdict', 'offline_normalized_prediction', 
        'offline_tokens', 'offline_cost', 'offline_duration_seconds',
        'offline_papers_analyzed', 'offline_relevant_chunks'
    ]
    hybrid_cols = [
        'hybrid_agent_verdict', 'hybrid_normalized_prediction', 
        'hybrid_tokens', 'hybrid_cost', 'hybrid_duration_seconds',
        'hybrid_papers_analyzed', 'hybrid_relevant_chunks'
    ]
    
    fieldnames = base_cols + offline_cols + hybrid_cols + ['error']
    
    print(f"\nWriting combined results to {OUTPUT_COMPARISON_CSV}...")
    with open(OUTPUT_COMPARISON_CSV, 'w') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for row in sample_rows:
            compound = row['IUPAC name']
            
            # Update with offline data
            res_off = results_offline.get(compound, {})
            row.update(res_off)
            
            # Update with hybrid data
            res_hyb = results_hybrid.get(compound, {})
            row.update(res_hyb)
            
            writer.writerow(row)
            
    # Cleanup
    for s in [script_offline, script_hybrid]:
        if os.path.exists(s):
            os.remove(s)
    # Optional: Keep JSONs for debugging, or remove? 
    # os.remove('temp_offline_results.json')
    # os.remove('temp_hybrid_results.json')
        
    print("Done! Comparison complete.")

if __name__ == "__main__":
    main()
