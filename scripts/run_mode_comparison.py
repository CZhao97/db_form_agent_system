#!/usr/bin/env python3
"""
Compare DBP Agent verdicts between Offline-Only and Online-Only modes.
Run this to verify both search components work correctly in isolation.
"""
import os
import sys
import subprocess
import json
from pathlib import Path

# Test compounds
import random

# --- Load Candidate Pool from Extracted JSON ---
pool_path = os.path.join(os.path.dirname(__file__), "dbp_pool.json")
try:
    with open(pool_path, 'r') as f:
        CANDIDATE_POOL = json.load(f)
    print(f"Loaded {len(CANDIDATE_POOL)} candidates from {pool_path}")
except Exception as e:
    print(f"Error loading pool: {e}")
    # Fallback/Empty to prevent crash, though user expects this to work
    CANDIDATE_POOL = []

# Hardcoded debug target from USER REQUEST
# "Consistency Check" (5 Samples)
# New Failed Cases from SOTA Benchmark (for Regression Testing)
SELECTED_COMPOUNDS = [
    # "2,6-Dibromo-4-[1-[3,5-dibromo-4-(2,6-dibromo-4-hydroxyphenoxy)phenyl]-1-methylethyl]phenol",
    # "3,4,5-Trihydroxy-2,6-diiodobenzenesulfonic acid",
    "2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione", # TBBQ
    "2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione", # TBBQ
    "2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione", # TBBQ
    # "1,3,6-Tribromo-9H-carbazole",
    # "2,6-Dibromo-4-nonylphenol",
    # "2-Hydroxy-3,5-diiodobenzaldehyde",
    # "4,5-Diiodo-2,3-dimethylphenol" # Negative Control
]

OFFLINE_COMPOUNDS = SELECTED_COMPOUNDS
ONLINE_COMPOUNDS = SELECTED_COMPOUNDS
print(f"DEBUG: Selected target for comparison: {SELECTED_COMPOUNDS}")

def create_driver_script(mode_name, compounds, env_vars):
    """Create a temporary Python script that runs evaluation with specific env vars."""
    
    driver_code = f'''
import sys
import os
import json

# Set environment before importing modules
for key, val in {env_vars}.items():
    os.environ[key] = val

# Add paths to handle sibling imports correctly
sys.path.insert(0, os.path.join(os.getcwd(), "notebooks"))
sys.path.insert(0, os.getcwd())

from evaluate_dbp_downstream_only import evaluate_compound

from langchain_community.callbacks import get_openai_callback
 
compounds = {compounds}
 
print(f"\\n{'='*60}")
print(f"MODE: {mode_name}")
print(f"{'='*60}\\n")
 
results = []
for compound in compounds:
    print(f"\\n>>> Processing: {{compound}} <<<")
    try:
        with get_openai_callback() as cb:
            result = evaluate_compound(compound)
        result["tokens_used"] = cb.total_tokens
        result["cost_usd"] = round(cb.total_cost, 6)
        results.append(result)
        print(f"Result: {{result['normalized_prediction']}} (Raw: {{str(result['agent_verdict'])[:50]}}...) (Tokens: {{result['tokens_used']}})")
    except Exception as e:
        print(f"ERROR processing {{compound}}: {{e}}")
        results.append({{'input_compound': compound, 'agent_verdict': 'Error'}})

# Print summary
print(f"\\n{'='*60}")
print(f"SUMMARY: {mode_name}")
print(f"{'='*60}")
for r in results:
    print(f"{{r['input_compound']:30s}} -> {{r['agent_verdict']}}")
'''
    
    script_path = f"temp_driver_{mode_name.lower().replace(' ', '_')}.py"
    with open(script_path, 'w') as f:
        f.write(driver_code)
    
    return script_path

def run_mode(mode_name, compounds, env_vars):
    """Run evaluation in specified mode."""
    print(f"\n{'#'*70}")
    print(f"# STARTING: {mode_name}")
    print(f"# Compounds: {{compounds}}")
    print(f"# Env: {env_vars}")
    print(f"{'#'*70}\n")
    
    driver_script = create_driver_script(mode_name, compounds, env_vars)
    
    try:
        # Merge with current environment
        current_env = os.environ.copy()
        current_env.update(env_vars)
        
        # Run from 'notebooks' directory to ensure relative paths work if needed
        # We run from CWD but driver handles sys.path
        
        # Log file for this run
        log_file = f"stability_test_{mode_name.lower().replace(' ', '_')}.log"
        print(f"Streaming logs to {log_file}...")
        
        with open(log_file, "w") as outfile:
            result = subprocess.run(
                [sys.executable, driver_script],
                env=current_env,
                # Capture both stdout/stderr and pipe to file AND terminal (tee-like behavior impossible with run, so mostly file)
                # Actually, capturing to file is better for analysis.
                stdout=outfile,
                stderr=subprocess.STDOUT, 
                text=True
            )
        
        # Print the output to terminal as well for immediate visibility
        with open(log_file, "r") as infile:
            print(infile.read())
            
        if result.returncode != 0:
            print(f"WARNING: {mode_name} exited with code {result.returncode}")
            
    except KeyboardInterrupt:
        print(f"\n{mode_name} interrupted by user")
    finally:
        # Cleanup
        if os.path.exists(driver_script):
            os.remove(driver_script)

def main():
    print("\n" + "="*70)
    print("DBP AGENT ONLINE RECONCILIATION RUN")
    print("="*70)
    print(f"Re-running Online Mode for the previously selected 10 compounds.")
    print("")
    
    # # Mode 1: Offline Only
    # run_mode(
    #     mode_name="OFFLINE ONLY",
    #     compounds=OFFLINE_COMPOUNDS,
    #     env_vars={
    #         "INCLUDE_OFFLINE_SEARCH": "True", # Explicitly enabled
    #         "INCLUDE_ONLINE_SEARCH": "False",  # Explicitly disabled
    #         "LANGCHAIN_PROJECT": "DBP_Comparison_Offline" # Organized Logging
    #     }
    # )

    # Mode 2: Online Only (Repeated 3 times for consistency check)
    target_compound = ["2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione"] # TBBQ
    
    for i in range(1, 4):
        run_label = f"ONLINE ONLY RUN {i}"
        print(f"\n--- Starting {run_label} ---")
        run_mode(
            mode_name=run_label,
            compounds=target_compound,
            env_vars={
                "INCLUDE_OFFLINE_SEARCH": "False",
                "INCLUDE_ONLINE_SEARCH": "True",
                "LANGCHAIN_PROJECT": f"DBP_Stability_Test_Run_{i}",
                "LANGCHAIN_DEBUG": "true", # Capture full chain trace (reasoning & actions)
                "NODE_LOGS": "1"
            }
        )
    
    print("\n" + "="*70)
    print("COMPARISON COMPLETE")
    print("="*70)
    
    print("\n" + "="*70)
    print("COMPARISON COMPLETE")
    print("="*70)
    print("\nCheck the verdicts above to compare agent behavior.")

if __name__ == "__main__":
    main()
