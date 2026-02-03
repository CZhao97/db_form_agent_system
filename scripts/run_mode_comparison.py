#!/usr/bin/env python3
"""
Compare DBP Agent verdicts between Offline-Only and Hybrid modes.
Run this to generate data for the manuscript (Coverage vs Efficiency).

Usage:
    python scripts/run_mode_comparison.py --sample --limit 50
    python scripts/run_mode_comparison.py --compounds "Compound A" "Compound B"
"""
import os
import sys
import subprocess
import json
import csv
import random
import time
import argparse
from pathlib import Path

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "evaluation_results_full_fresh_k10.csv")
OUTPUT_CSV = os.path.join(BASE_DIR, "comparison_results_offline_vs_hybrid.csv")

def create_driver_script(mode_name, compounds, env_vars):
    """Create a temporary Python script that runs evaluation with specific env vars."""
    
    driver_code = f'''
import sys
import os
import json
import time

# Set environment before importing modules
for key, val in {json.dumps(env_vars)}.items():
    os.environ[key] = val

# Add paths to handle sibling imports correctly
sys.path.insert(0, os.path.join('{BASE_DIR}', "notebooks"))
sys.path.insert(0, '{BASE_DIR}')

from langchain_community.callbacks import get_openai_callback

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
mode_name = "{mode_name}"
results_map = {{}}
temp_file = f"temp_{{mode_name}}_results.json"

# Load existing if any (for resume capability)
if os.path.exists(temp_file):
    try:
        with open(temp_file, 'r') as f:
            results_map = json.load(f)
    except:
        pass

print(f"\\n{'='*60}")
print(f"MODE: {{mode_name}}")
print(f"{{'='*60}}\\n")

for i, compound in enumerate(compounds):
    if compound in results_map:
        print(f"[{{i+1}}/{{len(compounds)}}] Skipping already done: {{compound}}")
        continue

    print(f"\\n>>> [{{i+1}}/{{len(compounds)}}] Processing: {{compound}} <<<")
    try:
        start_time = time.time()
        with get_openai_callback() as cb:
            result = evaluate_compound(compound)
        end_time = time.time()
        duration = end_time - start_time
        
        # Extract fields
        verdict = result.get('agent_verdict', 'Error')
        norm_pred = result.get('normalized_prediction', 'Error')
        
        # Parse coverage info
        papers_analyzed = result.get('papers_analyzed', 0)
        relevant_chunks = result.get('relevant_chunks', 0)
        
        # Fallback parsing if coverage not in result dict
        try:
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
            'agent_verdict': verdict,
            'normalized_prediction': norm_pred,
            'tokens_used': cb.total_tokens,
            'cost_usd': round(cb.total_cost, 6),
            'duration_seconds': round(duration, 2),
            'papers_analyzed': papers_analyzed,
            'relevant_chunks': relevant_chunks
        }}
        
        print(f"Result: {{norm_pred}} (Time: {{duration:.2f}}s, Papers: {{papers_analyzed}})")
        
    except Exception as e:
        print(f"ERROR processing {{compound}}: {{e}}")
        results_map[compound] = {{
            'agent_verdict': 'Error',
            'normalized_prediction': 'Error',
            'tokens_used': 0,
            'cost_usd': 0.0,
            'duration_seconds': 0.0,
            'papers_analyzed': 0,
            'relevant_chunks': 0,
            'error': str(e)
        }}

    # Incremental save
    with open(temp_file, 'w') as f:
        json.dump(results_map, f, indent=2)
'''
    
    script_path = f"temp_driver_{mode_name.lower().replace(' ', '_')}.py"
    with open(script_path, 'w') as f:
        f.write(driver_code)
    
    return script_path

def main():
    parser = argparse.ArgumentParser(description="Run DBP Agent Mode Comparison (Offline vs Hybrid)")
    parser.add_argument("--sample", action="store_true", help="Sample random compounds from CSV")
    parser.add_argument("--limit", type=int, default=50, help="Number of compounds (default 50)")
    parser.add_argument("--compounds", nargs="+", help="Specific compounds to run")
    parser.add_argument("--csv", default=OUTPUT_CSV, help="Output CSV path")
    args = parser.parse_args()

    compounds = []
    sample_rows = []

    # 1. Determine Compounds
    if args.sample:
        if not os.path.exists(CSV_PATH):
            print(f"Error: CSV file not found at {CSV_PATH}")
            sys.exit(1)
        
        print(f"Reading {CSV_PATH}...")
        with open(CSV_PATH, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        random.seed(42)
        if len(rows) > args.limit:
            sample_rows = random.sample(rows, args.limit)
        else:
            sample_rows = rows
        
        compounds = [r['IUPAC name'] for r in sample_rows]
        print(f"Sampled {len(compounds)} compounds.")
    
    elif args.compounds:
        compounds = args.compounds
        # Create dummy rows for explicit compounds
        sample_rows = [{'IUPAC name': c} for c in compounds]
        print(f"Using {len(compounds)} explicitly provided compounds.")
    
    else:
        # Default/Legacy behavior
        compounds = ["2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione"]
        sample_rows = [{'IUPAC name': c} for c in compounds]
        print(f"Using default target: {compounds}")

    # 2. Define Env Modes
    # Note: Tracking disabled to speed up loop
    base_env = {
        "LANGCHAIN_TRACING_V2": "false",
        "LANGCHAIN_ENDPOINT": "",
        "LANGCHAIN_API_KEY": ""
    }
    
    env_offline = base_env.copy()
    env_offline.update({
        "INCLUDE_OFFLINE_SEARCH": "True",
        "INCLUDE_ONLINE_SEARCH": "False",
        "LANGCHAIN_PROJECT": "DBP_Compar_Offline"
    })
    
    env_hybrid = base_env.copy()
    env_hybrid.update({
        "INCLUDE_OFFLINE_SEARCH": "True",
        "INCLUDE_ONLINE_SEARCH": "True",
        "LANGCHAIN_PROJECT": "DBP_Compar_Hybrid"
    })

    # 3. Run Offline Pass
    print("\n" + "="*70)
    print("STARTING PASS 1: OFFLINE ONLY")
    print("="*70)
    script_offline = create_driver_script("offline", compounds, env_offline)
    try:
        subprocess.run([sys.executable, script_offline], check=True)
    except subprocess.CalledProcessError:
        print("Warning: Offline pass had errors.")

    # 4. Run Hybrid Pass
    print("\n" + "="*70)
    print("STARTING PASS 2: HYBRID (ONLINE + OFFLINE)")
    print("="*70)
    script_hybrid = create_driver_script("hybrid", compounds, env_hybrid)
    try:
        subprocess.run([sys.executable, script_hybrid], check=True)
    except subprocess.CalledProcessError:
        print("Warning: Hybrid pass had errors.")

    # 5. Merge Results
    print("\nMerging results...")
    results_offline = {}
    if os.path.exists('temp_offline_results.json'):
         with open('temp_offline_results.json', 'r') as f:
             results_offline = json.load(f)

    results_hybrid = {}
    if os.path.exists('temp_hybrid_results.json'):
         with open('temp_hybrid_results.json', 'r') as f:
             results_hybrid = json.load(f)
    
    # Define Output Columns
    # Base columns + Mode specific columns
    base_cols = [k for k in sample_rows[0].keys() if k != 'IUPAC name']
    # Ensure IUPAC name is first
    final_cols = ['IUPAC name'] + base_cols
    
    modes = [('offline', results_offline), ('hybrid', results_hybrid)]
    metrics = ['agent_verdict', 'normalized_prediction', 'tokens_used', 'cost_usd', 'duration_seconds', 'papers_analyzed', 'relevant_chunks']
    
    for mode_name, _ in modes:
        for m in metrics:
            final_cols.append(f"{mode_name}_{m}")
    
    final_cols.append('error')

    print(f"Writing to {args.csv}...")
    with open(args.csv, 'w') as f:
        writer = csv.DictWriter(f, fieldnames=final_cols)
        writer.writeheader()
        
        for row in sample_rows:
            compound = row['IUPAC name']
            out_row = row.copy()
            
            # Enrich
            for mode_name, res_map in modes:
                data = res_map.get(compound, {})
                for m in metrics:
                    out_row[f"{mode_name}_{m}"] = data.get(m, "")
            
            writer.writerow(out_row)
            
    # Cleanup
    for s in [script_offline, script_hybrid]:
        if os.path.exists(s):
            os.remove(s)
            
    print("Done.")

if __name__ == "__main__":
    main()
