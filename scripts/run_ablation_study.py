import os
import sys
import pandas as pd
import json
import time
import argparse
import random
from langchain_community.callbacks import get_openai_callback

# Add local path to import evaluation function
sys.path.append(os.path.join(os.getcwd(), 'notebooks'))
try:
    from evaluate_dbp_downstream_only import evaluate_compound
except ImportError:
    print("Error importing evaluate_compound. Make sure you are in the correct directory.")
    sys.exit(1)

OUTPUT_DIR = "agent/searching_results/ablation_study"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 2. Define Conditions
CONDITIONS = {
    # "Baseline": {
    #    "ENABLE_CRITIQUE_AGENT": "True"
    # },
    "No_Critique": {
        "ENABLE_CRITIQUE_AGENT": "False"
    }
}

def load_benchmark_data(args):
    """
    Loads benchmark data. 
    Assumes inputs are POSITIVE samples (Ground Truth = 1).
    Can optionally add Negatives if a file is provided.
    """
    data = []
    
    # 1. Load Positive DBPs (The Benchmark)
    bp_path = "/home/chen/GNPS_SIM/agent/db_form_agent_system/notebooks/dbp_gemini_flash_2_5_results.xlsx"
    if os.path.exists(bp_path):
        print(f"Loading positives from {bp_path}...")
        df = pd.read_excel(bp_path)
        # Use IUPAC name or Preferred DBP name
        col = 'IUPAC name' if 'IUPAC name' in df.columns else 'Preferred DBP name'
        
        # Sample or Full
        if not args.full:
             df = df.head(10) # Test with 10
             print("TEST MODE: Loaded top 10 rows.")
             
        for name in df[col].dropna().unique():
            data.append({"Compound": name, "GroundTruth": 1})
        print(f"Loaded {len(data)} positive samples.")
    else:
        print(f"Warning: Benchmark file {bp_path} not found. Using dummy set.")
        data = [
            {"Compound": "Chloroform", "GroundTruth": 1},
            {"Compound": "Bromoform", "GroundTruth": 1}
        ]

    # 2. Add some negatives for Precision calculaton?
    # Ideally we'd load `hmdb` metabolites but for now let's stick to the manual list mixed in if it's a test?
    # Or just run on what we have. If we only have positives, Precision is physically impossible to measure (TP/TP).
    # We will assume Recalls are the main metric if only Positives are present.
    
    # For a robust "full run", let's include the manual negatives to roughly check FP.
    negatives = ["Sucrose", "Ascorbic acid", "Sodium chloride"]
    for n in negatives:
        data.append({"Compound": n, "GroundTruth": 0})
        
    return data

def run_condition(condition_name, env_vars, dataset):
    print(f"\n--- Running Condition: {condition_name} ---")
    
    # Set Env Vars
    for k, v in env_vars.items():
        os.environ[k] = v
    
    # LangSmith Debugging
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = f"ABLATION_{condition_name}_{time.strftime('%H%M')}"
    
    print(f"[DEBUG] Condition: {condition_name}")
    print(f"[DEBUG] ENABLE_CRITIQUE_AGENT set to: {os.environ.get('ENABLE_CRITIQUE_AGENT')}")
        
    # Resume logic: Check if output file exists
    timestamp = time.strftime("%Y%m%d") # Use Day level for resume stability or check dir
    # Actually, we should use a fixed filename for the run or pass it in. 
    # For simplicity, let's look for any partial file in the dir or just use a fixed name for this "session".
    save_path = f"{OUTPUT_DIR}/ablation_results_FULL_RESUME.csv"
    
    completed_keys = set()
    all_results = [] # Fix: Initialize here
    
    if os.path.exists(save_path):
        try:
            existing_df = pd.read_csv(save_path)
            # Create unique key: Condition + Compound
            for _, row in existing_df.iterrows():
                completed_keys.add(f"{row['Condition']}_{row['Compound']}")
            print(f"Resuming... Found {len(completed_keys)} completed entries in {save_path}")
            all_results = existing_df.to_dict('records')
        except Exception:
            print("Error reading existing resume file, starting fresh.")
            all_results = []
    
    # results local list for this condition
    results = []

    # Run evaluation
    for item in dataset:
        compound = item["Compound"]
        ground_truth = item["GroundTruth"]
        
        # Check resume
        if f"{condition_name}_{compound}" in completed_keys:
            print(f"  Skipping {compound} (Already processed)")
            continue
        
        print(f"  Verifying: {compound}...")
        try:
            res = evaluate_compound(compound, base_results_dir=os.path.join(OUTPUT_DIR, condition_name)) 
            verdict = res.get('normalized_prediction', 'Error')
            
            # Map verdict to binary
            is_positive = 1 if "Confirmed" in str(verdict) or "confirmed" in str(verdict) or verdict == "True" else 0
            
            is_correct = (is_positive == ground_truth)
            
            result_entry = {
                "Condition": condition_name,
                "Compound": compound,
                "GroundTruth": ground_truth,
                "Verdict": verdict,
                "IsPositive": is_positive,
                "IsCorrect": is_correct
            }
            results.append(result_entry)
            all_results.append(result_entry)
            
            # Incremental Save
            pd.DataFrame(all_results).to_csv(save_path, index=False)
            
            print(f"    -> {verdict} (Correct: {is_correct})")
            
        except Exception as e:
            print(f"    -> Error: {e}")
            # Save error state too to avoid infinite retry loop on crash (or maybe we WANTS retry? Let's save error)
            result_entry = {
                "Condition": condition_name,
                "Compound": compound,
                "GroundTruth": ground_truth,
                "Verdict": f"Error: {str(e)}",
                "IsPositive": -1,
                "IsCorrect": False
            }
            results.append(result_entry)
            all_results.append(result_entry)
            pd.DataFrame(all_results).to_csv(save_path, index=False)

    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Run on full benchmark")
    args = parser.parse_args()
    
    dataset = load_benchmark_data(args)
    print(f"Total dataset size: {len(dataset)}")
    
    all_results = []
    
    # Global Settings
    os.environ["INCLUDE_ONLINE_SEARCH"] = "True"
    
    for cond_name, env_vars in CONDITIONS.items():
        # Pass the global all_results list implicitly via file reload or just append logic in run_condition
        # Actually run_condition handles the file saving now.
        res = run_condition(cond_name, env_vars, dataset)
        # all_results is managed inside run_condition via the file load/save
        
    print(f"\nSaved full results to {OUTPUT_DIR}/ablation_results_FULL_RESUME.csv")
    
    # Reload for stats
    try:
        df = pd.read_csv(f"{OUTPUT_DIR}/ablation_results_FULL_RESUME.csv")
        
        # Generate Stats
        stats = []
        for cond_name in CONDITIONS.keys():
            sub = df[df["Condition"] == cond_name]
            tp = len(sub[(sub["IsPositive"] == 1) & (sub["GroundTruth"] == 1)])
            fp = len(sub[(sub["IsPositive"] == 1) & (sub["GroundTruth"] == 0)])
            fn = len(sub[(sub["IsPositive"] == 0) & (sub["GroundTruth"] == 1)])
            
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            
            stats.append({
                "Condition": cond_name,
                "Precision": precision,
                "Recall": recall,
                "TP": tp, "FP": fp, "FN": fn
            })
            
        stats_df = pd.DataFrame(stats)
        print("\n--- Detailed Metrics ---")
        print(stats_df)
        stats_df.to_csv(f"{OUTPUT_DIR}/ablation_metrics_RESUME.csv", index=False)
    except Exception as e:
        print(f"Could not generate stats: {e}")

if __name__ == "__main__":
    main()
