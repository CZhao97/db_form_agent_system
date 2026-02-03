import pandas as pd
import sys
import os
import time
from langchain_community.callbacks import get_openai_callback

# Add path to code
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "notebooks"))

CSV_PATH = "comparison_results_offline_vs_hybrid.csv"
TARGET_COMPOUND = "4-Hydroxy-3-iodobenzoic acid"

def main():
    print(f"Reading {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH)
    
    # Find index
    mask = df['IUPAC name'] == TARGET_COMPOUND
    if not mask.any():
        print(f"Compound {TARGET_COMPOUND} not found in CSV.")
        return
    idx = df[mask].index[0]
    
    print(f"Rescuing Hybrid run for: {TARGET_COMPOUND} (Index {idx})")
    
    # Set Environment for HYBRID searching
    os.environ["INCLUDE_OFFLINE_SEARCH"] = "True"
    os.environ["INCLUDE_ONLINE_SEARCH"] = "True"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = "DBP_Agent_Rescue_Hybrid_Run"
    os.environ["AGENT_RECURSION_LIMIT"] = "20"
    
    try:
        from evaluate_dbp_downstream_only import evaluate_compound
    except ImportError:
        sys.path.append(os.getcwd())
        from evaluate_dbp_downstream_only import evaluate_compound

    try:
        start_time = time.time()
        with get_openai_callback() as cb:
            # Note: evaluate_compound usually defaults to using env vars for tool config
            result = evaluate_compound(TARGET_COMPOUND)
        duration = time.time() - start_time
        
        print(f"Result: {result.get('agent_verdict')}")
        
        # Update DataFrame
        df.at[idx, 'hybrid_agent_verdict'] = result.get('agent_verdict', 'Error')
        df.at[idx, 'hybrid_normalized_prediction'] = result.get('normalized_prediction', 'Error')
        df.at[idx, 'hybrid_tokens_used'] = cb.total_tokens
        df.at[idx, 'hybrid_cost_usd'] = cb.total_cost
        df.at[idx, 'hybrid_duration_seconds'] = duration
        df.at[idx, 'hybrid_papers_analyzed'] = result.get('papers_analyzed', 0)
        df.at[idx, 'hybrid_relevant_chunks'] = result.get('relevant_chunks', 0)
        df.at[idx, 'error'] = "" # Clear error flag if any?
        
        df.to_csv(CSV_PATH, index=False)
        print(f"Updated {CSV_PATH}")
        
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    main()
