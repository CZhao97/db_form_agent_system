import os
import sys
import pandas as pd
import time
from langchain_community.callbacks import get_openai_callback

# Add local path to import evaluation function
sys.path.append(os.path.join(os.getcwd(), 'notebooks'))
try:
    from evaluate_dbp_downstream_only import evaluate_compound
except ImportError:
    print("Error importing evaluate_compound.")
    sys.exit(1)

OUTPUT_DIR = "agent/searching_results/ablation_study"
os.makedirs(OUTPUT_DIR, exist_ok=True)
RERUN_FILE = f"{OUTPUT_DIR}/ablation_results_errors_fixed.csv"

def normalize_verdict(verdict):
    """Normalize text verdict to score (0/1) for consistent IsPositive check."""
    s = str(verdict).lower()
    if 'not confirmed' in s: return 0
    if 'confirmed' in s: return 1
    if verdict == "True": return 1
    return 0

def run_errors():
    # 1. Load Errors from Comparison
    print("Loading errors from final_ablation_comparison.csv...")
    try:
        df_comp = pd.read_csv("final_ablation_comparison.csv")
    except FileNotFoundError:
        print("Comparison file not found!")
        return

    # Filter for Error in Ablation_Verdict
    # Note: in previous step we saw it was just "Error" string.
    errors_df = df_comp[df_comp['Ablation_Verdict'].astype(str).str.contains("Error", case=False, na=False)]
    
    compounds_to_run = errors_df['Compound'].tolist()
    print(f"Found {len(compounds_to_run)} compounds to rerun.")
    
    if not compounds_to_run:
        print("No errors to run.")
        return

    # 2. Set Environment for Ablation (No Critique) + Higher Limit
    os.environ["ENABLE_CRITIQUE_AGENT"] = "False"
    os.environ["AGENT_RECURSION_LIMIT"] = "50" # Double the limit
    
    print(f"Environment: ENABLE_CRITIQUE_AGENT={os.environ['ENABLE_CRITIQUE_AGENT']}")
    print(f"Environment: AGENT_RECURSION_LIMIT={os.environ['AGENT_RECURSION_LIMIT']}")
    
    # 3. Run Loop
    results = []
    
    # Check if partial run exists
    if os.path.exists(RERUN_FILE):
        existing = pd.read_csv(RERUN_FILE)
        results = existing.to_dict('records')
        processed = set(existing['Compound'].unique())
        print(f"Resuming {RERUN_FILE}, {len(processed)} already done.")
        compounds_to_run = [c for c in compounds_to_run if c not in processed]
    
    print(f"Remaining to run: {len(compounds_to_run)}")
    
    for i, compound in enumerate(compounds_to_run):
        print(f"[{i+1}/{len(compounds_to_run)}] Retrying: {compound}...")
        
        try:
            # We assume GroundTruth is 1 for these (since they came from the positive set originally? 
            # Wait, comparison file has GroundTruth column. Let's look it up or just assume.
            # actually better to look it up from errors_df
            gt_row = errors_df[errors_df['Compound'] == compound]
            gt = gt_row['GroundTruth'].values[0] if not gt_row.empty else 1
            
            res = evaluate_compound(compound, base_results_dir=os.path.join(OUTPUT_DIR, "No_Critique_Rerun"))
            verdict = res.get('normalized_prediction', 'Error')
            
            # Map verdict
            is_positive = normalize_verdict(verdict)
            
            result_entry = {
                "Condition": "No_Critique",
                "Compound": compound,
                "GroundTruth": gt,
                "Verdict": verdict,
                "IsPositive": is_positive,
                "IsCorrect": (is_positive == gt)
            }
            results.append(result_entry)
            
            # Save incrementally
            pd.DataFrame(results).to_csv(RERUN_FILE, index=False)
            print(f"   -> {verdict}")
            
        except Exception as e:
            print(f"   -> Error: {e}")
            # If it fails again, record Error
            results.append({
                "Condition": "No_Critique",
                "Compound": compound,
                "GroundTruth": 1, # Default
                "Verdict": f"Error: {str(e)}",
                "IsPositive": 0,
                "IsCorrect": False
            })
            pd.DataFrame(results).to_csv(RERUN_FILE, index=False)

if __name__ == "__main__":
    run_errors()
