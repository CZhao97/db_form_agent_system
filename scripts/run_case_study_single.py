import os
import sys
import pandas as pd
import logging

# Add local path to import evaluation function
sys.path.append(os.path.join(os.getcwd(), 'notebooks'))
from evaluate_dbp_downstream_only import evaluate_compound

# Setup Logging to capture the trace
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("case_study_candidates.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

def run_case():
    # Candidates
    candidates = ["Oxcarbazepine", "Valine"]
    
    print(f"Running Case Study candidates: {candidates}")
    
    # Ensure Critique is ENABLED for full verification context
    os.environ["ENABLE_CRITIQUE_AGENT"] = "True"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = "Case_Study_Rerun"
    
    results = []
    
    for compound in candidates:
        print(f"\n--- Processing: {compound} ---")
        try:
            # We use a dummy base_results_dir, evaluate_compound handles the rest
            res = evaluate_compound(compound, base_results_dir="agent/searching_results/case_study")
            print(f"Result for {compound}: {res}")
            results.append({"Compound": compound, "Result": res})
        except Exception as e:
            print(f"Error processing {compound}: {e}")

if __name__ == "__main__":
    try:
        # multiprocessing fix
        import multiprocessing as mp
        try:
            mp.set_start_method('spawn', force=True)
        except RuntimeError:
            pass
            
        run_case()
    except Exception as e:
        print(f"Script failed: {e}")
