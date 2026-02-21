import json
import random
import os
import sys
import pandas as pd
from pathlib import Path
# from langchain_openai import ChatOpenRouter
from langchain_core.messages import SystemMessage, HumanMessage

# Add path to import local modules
sys.path.append(os.path.join(os.getcwd(), 'notebooks'))
try:
    from evaluate_dbp_downstream_only import evaluate_compound
except ImportError:
    pass

# Import the batch generation function (we will modify/call it or replicate logic)
# To avoid complex imports, I will rely on the output file of batch_query_gen which we will run first.

BENCHMARK_FILE = "scripts/dbp_pool.json"
OUTPUT_DIR = "agent/searching_results/de_novo_experiment"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_benchmark():
    with open(BENCHMARK_FILE, 'r') as f:
        data = json.load(f)
    # Simplify names for matching (lowercase)
    return set([n.lower().strip() for n in data])

def get_candidates_from_batch_output(jsonl_path):
    candidates = []
    with open(jsonl_path, 'r') as f:
        for line in f:
            data = json.loads(line)
            # Extract name from the query string which is "decide whether 'NAME' is..."
            import re
            query = data.get("query", "")
            match = re.search(r"decide whether '(.*?)' is", query)
            if match:
                candidates.append(match.group(1))
    return list(set(candidates))

def main():
    print("--- Starting De Novo Experiment ---")
    
    # 1. Run Batch Generation (if not already done for a large set)
    # Ideally, we assume batch_query_gen.py has been run. 
    # But for this script, let's assume we consume the output of the recent test run or we just run it now.
    # To be safe, let's run batch_query_gen.py process on 2000 items (40 batches).
    # We will modify batch_query_gen.py dynamically or just trust the existing output if it exists.
    # For now, let's use the 'recovered_queries_test_200.jsonl' as a pilot. 
    # If the user wants 2000, they can run `batch_query_gen.py` separately with a larger limit.
    import os
    from pathlib import Path
    BASE_DIR = Path("/home/chen/GNPS_SIM/agent/db_form_agent_system")
    
    # Source File (Output from batch_query_gen.py)
    # Using the full recovered file found on disk
    SOURCE_FILE = BASE_DIR / "agent/searching_results/e2e_run_20260125_130247/recovered_queries_full.json" # This will be the source
    
    print(f"Loading candidates from {SOURCE_FILE}...")
    if not os.path.exists(SOURCE_FILE):
        print("Source file not found. Please run batch_query_gen.py first.")
        return

    extracted_candidates = get_candidates_from_batch_output(SOURCE_FILE)
    print(f"Total Extracted Candidates: {len(extracted_candidates)}")
    
    # 2. Filter for Novelty
    benchmark_set = load_benchmark()
    novel_candidates = []
    
    for cand in extracted_candidates:
        if cand.lower().strip() not in benchmark_set:
            novel_candidates.append(cand)
            
    print(f"Novel Candidates (Not in Benchmark): {len(novel_candidates)}")
    print(f"Novelty Rate: {len(novel_candidates)/len(extracted_candidates)*100:.1f}%")
    
    # 3. Random Sample for Verification
    SAMPLE_SIZE = 300 # Sample size for the pilot. User can increase.
    if len(novel_candidates) > SAMPLE_SIZE:
        verification_sample = random.sample(novel_candidates, SAMPLE_SIZE)
    else:
        verification_sample = novel_candidates
        
    print(f"Verifying sample of {len(verification_sample)} candidates...")
    
    results = []
    save_path = f"{OUTPUT_DIR}/de_novo_results.csv"
    
    # RESUME LOGIC
    completed_compounds = set()
    if os.path.exists(save_path):
        try:
            df_existing = pd.read_csv(save_path)
            completed_compounds = set(df_existing["Compound"].unique())
            results = df_existing.to_dict('records')
            print(f"Resume: Found {len(completed_compounds)} already verified compounds.")
        except Exception:
            print("Resume file unreadable, starting fresh.")

    # Setup Environment for Agent
    os.environ["INCLUDE_OFFLINE_SEARCH"] = "True" 
    os.environ["INCLUDE_ONLINE_SEARCH"] = "True" 
    os.environ["LANGCHAIN_PROJECT"] = "DBP_De_Novo_Experiment"
    
    from langchain_community.callbacks import get_openai_callback
    
    verified_count = 0
    # Recalculate verified count from resume
    for r in results:
        if r.get("Prediction") == "Confirmed":
            verified_count += 1
    
    BLACKLIST = ["4-(1-carboxyethyl)benzoic acid"]
    for i, compound in enumerate(verification_sample):
        if compound in BLACKLIST:
            print(f"[{i+1}/{len(verification_sample)}] Skipping {compound} (Blacklisted/Crash Prone)")
            continue

        if compound in completed_compounds:
            print(f"[{i+1}/{len(verification_sample)}] Skipping {compound} (Already done)")
            continue
            
        print(f"[{i+1}/{len(verification_sample)}] Verifying: {compound}")
        try:
            with get_openai_callback() as cb:
                 # We import here to ensure env vars are picked up
                 from evaluate_dbp_downstream_only import evaluate_compound
                 res = evaluate_compound(compound)
                 
            verdict = res.get('agent_verdict', 'Error')
            prediction = res.get('normalized_prediction', 'Error')
            
            print(f"  -> Verdict: {verdict} ({prediction})")
            
            if prediction == "Confirmed":
                verified_count += 1
                
            entry = {
                "Compound": compound,
                "Verdict": verdict,
                "Prediction": prediction,
                "Papers": res.get('papers_analyzed', 0)
            }
            results.append(entry)
            
            # INCREMENTAL SAVE
            pd.DataFrame(results).to_csv(save_path, index=False)
            
        except Exception as e:
            print(f"  -> Error: {e}")
            entry = {
                "Compound": compound,
                "Verdict": "Error",
                "Prediction": "Error",
                "Error": str(e)
            }
            results.append(entry)
            pd.DataFrame(results).to_csv(save_path, index=False)

    # 4. Report
    df_res = pd.DataFrame(results)
    save_path = f"{OUTPUT_DIR}/de_novo_results.csv"
    df_res.to_csv(save_path, index=False)
    
    precision = (verified_count / len(verification_sample)) * 100 if verification_sample else 0
    
    report = f"""
    # De Novo Experiment Report
    
    - **Total Extracted**: {len(extracted_candidates)}
    - **Novel Candidates**: {len(novel_candidates)}
    - **Sample Verified**: {len(verification_sample)}
    - **Confirmed (Agent)**: {verified_count}
    - **Precision (Agent)**: {precision:.1f}%
    
    detailed results saved to {save_path}
    """
    
    print(report)
    with open(f"{OUTPUT_DIR}/report.md", "w") as f:
        f.write(report)

if __name__ == "__main__":
    main()
