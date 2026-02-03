import pandas as pd
import sys
import os
import json
import time
import argparse

# Add paths to allow imports
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "notebooks"))
sys.path.insert(0, BASE_DIR)

from langchain_community.callbacks import get_openai_callback
import fcntl

def update_csv_safely(csv_path, idx, updates):
    """Updates a single row in the CSV safely using file locking."""
    lock_path = csv_path + ".lock"
    with open(lock_path, "w") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            # Read fresh
            if os.path.exists(csv_path):
                df_curr = pd.read_csv(csv_path, index_col=0) # Assuming index 0 is the original index? No, read_csv adds RangeIndex unless index_col specified.
                # The original script does: df = pd.read_csv(CSV_PATH). 
                # If existing CSV has no index col, pandas creates one. 
                # df.loc[idx] uses label. 
                # We need to match the read method.
                # In main: df = pd.read_csv(CSV_PATH) -> Default RangeIndex 0..N
                # idx is from df[mask].index.tolist() -> integer labels.
                # So we should read without index_col, and use .at[idx]
                
                df_curr = pd.read_csv(csv_path)
                
                for col, val in updates.items():
                    df_curr.at[idx, col] = val
                    
                df_curr.to_csv(csv_path, index=False)
        except Exception as e:
            print(f"Failed to update main CSV: {e}")
        finally:
            fcntl.flock(lockfile, fcntl.LOCK_UN)




CSV_PATH = "comparison_results_offline_vs_hybrid.csv"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--num-shards", type=int, default=1)
    args = parser.parse_args()

    print(f"Reading {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH)
    
    # Identify gaps
    mask = df['offline_agent_verdict'].isna() | (df['offline_agent_verdict'] == "") | (df['offline_agent_verdict'] == "Error")
    missing_indices = df[mask].index.tolist()
    
    # Shard
    my_indices = [idx for i, idx in enumerate(missing_indices) if i % args.num_shards == args.shard]
    print(f"[Shard {args.shard}/{args.num_shards}] Processing {len(my_indices)} items (Total missing: {len(missing_indices)})")
    
    if len(my_indices) == 0:
        return

    # Output file for this shard
    shard_out = f"comparison_results_offline_shard_{args.shard}.csv"
    # Copy structure
    df_shard = df.loc[my_indices].copy()

    # Set up Environment
    # Set up Environment BEFORE any potential e2e_agent imports
    os.environ["INCLUDE_OFFLINE_SEARCH"] = "True"
    os.environ["INCLUDE_ONLINE_SEARCH"] = "False"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = "DBP_Agent_Rescue_Offline_Run"
    os.environ["AGENT_RECURSION_LIMIT"] = "20"
    
    # Lazy import to ensure env vars are respected
    try:
        from evaluate_dbp_downstream_only import evaluate_compound
        # Force reload if it was already imported? 
        # Actually, evaluate_compound lazy imports e2e_agent, so we are good if we touch env first.
    except ImportError:
        sys.path.append(os.getcwd())
        from evaluate_dbp_downstream_only import evaluate_compound

    for i, idx in enumerate(my_indices):
        compound = df.loc[idx, 'IUPAC name']
        print(f"\n[Shard {args.shard}] [{i+1}/{len(my_indices)}] Rescuing: {compound}")
        
        try:
            start_time = time.time()
            with get_openai_callback() as cb:
                result = evaluate_compound(compound)
            duration = time.time() - start_time
            
            # Update df_shard
            df_shard.at[idx, 'offline_agent_verdict'] = result.get('agent_verdict', 'Error')
            df_shard.at[idx, 'offline_normalized_prediction'] = result.get('normalized_prediction', 'Error')
            df_shard.at[idx, 'offline_tokens_used'] = cb.total_tokens
            df_shard.at[idx, 'offline_cost_usd'] = cb.total_cost
            df_shard.at[idx, 'offline_duration_seconds'] = duration
            df_shard.at[idx, 'offline_papers_analyzed'] = result.get('papers_analyzed', 0)
            df_shard.at[idx, 'offline_relevant_chunks'] = result.get('relevant_chunks', 0)
            
            
            df_shard.to_csv(shard_out, index=True) # Keep index to merge back
            print(f"  -> Saved to {shard_out}")

            # Update main CSV safely
            updates = {
                'offline_agent_verdict': result.get('agent_verdict', 'Error'),
                'offline_normalized_prediction': result.get('normalized_prediction', 'Error'),
                'offline_tokens_used': cb.total_tokens,
                'offline_cost_usd': cb.total_cost,
                'offline_duration_seconds': duration,
                'offline_papers_analyzed': result.get('papers_analyzed', 0),
                'offline_relevant_chunks': result.get('relevant_chunks', 0)
            }
            update_csv_safely(CSV_PATH, idx, updates)
            print(f"  -> Updated main file {CSV_PATH}")
            
        except Exception as e:
            print(f"  -> Failed: {e}")
            df_shard.at[idx, 'offline_agent_verdict'] = "Error"
            df_shard.to_csv(shard_out, index=True)

    print("\nRescue Complete.")

if __name__ == "__main__":
    main()
