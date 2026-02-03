
import sys
import os
import pandas as pd
import uuid
import time
import argparse
import json
import re
from pathlib import Path
from dotenv import load_dotenv
import multiprocessing as mp
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger("evaluate_recovered")

# --- SETUP PATHS ---
current_dir = os.getcwd()
notebooks_dir = os.path.abspath(os.path.join(current_dir, 'notebooks'))
code_dir = os.path.abspath(os.path.join(current_dir, 'agent/code'))

if notebooks_dir not in sys.path:
    sys.path.append(notebooks_dir)
if code_dir not in sys.path:
    sys.path.append(code_dir)

load_dotenv()

# --- HELPER: Extract Chemical Name ---
def extract_chemical_name(query_text):
    # Pattern to match: decide whether 'Chemical Name' is OR decide whether Chemical Name is
    # Try quoted first
    match = re.search(r"decide whether '([^']+)' is", query_text)
    if match:
        return match.group(1)
    
    # Try unquoted
    match = re.search(r"decide whether (.+?) is", query_text)
    if match:
        return match.group(1).strip()
        
    return "Unknown_Chemical"

# --- WORKER FUNCTION ---
def process_one_safe(args_tuple):
    if len(args_tuple) == 4:
         query_text, chemical_name, run_dir, gpu_queue = args_tuple
    else:
         query_text, chemical_name, run_dir = args_tuple
         gpu_queue = None

    # Setup GPU
    gpu_id = None
    if gpu_queue:
        try:
            gpu_id = gpu_queue.get(timeout=10)
        except Exception:
            gpu_id = None
    
    try:
        from e2e_agent import setup_gpu_worker
        setup_gpu_worker(gpu_id)
    except ImportError:
        pass

    result_row = {
        "chemical_name": chemical_name,
        "query": query_text,
        "status": "Failed",
        "agent_verdict": "Error",
        "normalized_prediction": "Error",
        "session_dir": ""
    }

    try:
        # Import inside worker to avoid issues
        from e2e_agent import (
            down_app, 
            determine_final_claim, 
            FullTextJournalSearchTool, 
            HumanMessage
        )
        from langchain_community.callbacks import get_openai_callback

        session_id = f"eval_rec_{uuid.uuid4().hex[:8]}"
        session_dir = os.path.join(run_dir, f"dbp_eval_{session_id}_{re.sub('[^A-Za-z0-9]+', '_', chemical_name)[:30]}")
        os.makedirs(session_dir, exist_ok=True)
        
        FullTextJournalSearchTool.set_session_dir(session_dir)

        initial_state = {
            "messages": [HumanMessage(content=query_text)],
            "original_query": query_text,
            "search_session_dir": session_dir,
            "stop_history": [],
            "claim_history": [],
            "confidence_history": [],
            "consecutive_no_new_evidence": 0,
            "consecutive_tool_unavailable": 0
        }
        
        config = {"configurable": {"thread_id": session_id}}
        
        log.info(f"Starting processing for: {chemical_name}")

        # ... inside process_one_safe ...
        with get_openai_callback() as cb:
             final_state = down_app.invoke(initial_state, config=config)
             claim = determine_final_claim(final_state["messages"])
        
        # New: Extract last node outputs
        last_researcher = final_state.get("last_researcher_json", "{}")
        last_critique = final_state.get("last_critique_json", "{}")

        # Parse verdict
        predicted = str(claim)
        if "{" in predicted:
             try:
                 data = json.loads(predicted[predicted.find("{"):predicted.rfind("}")+1])
                 if "verdict_statement" in data and "claim" in data["verdict_statement"]:
                     predicted = data["verdict_statement"]["claim"]
                 elif "claim" in data:
                     predicted = data["claim"]
             except:
                 pass
        
        result_row.update({
            "status": "Success",
            "agent_verdict": str(claim),
            "normalized_prediction": predicted,
            "session_dir": session_dir,
            "tokens_used": cb.total_tokens,
            "cost_usd": cb.total_cost,
            "last_researcher_json": last_researcher,
            "last_critique_json": last_critique
        })
        
    except Exception as e:
        log.error(f"Error processing {chemical_name}: {e}")
        result_row["normalized_prediction"] = f"Error: {e}"
        result_row["last_researcher_json"] = ""
        result_row["last_critique_json"] = ""
        
    finally:
        if gpu_queue and gpu_id is not None:
            gpu_queue.put(gpu_id)
            
    return result_row

def main():
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass
        
    import torch

    parser = argparse.ArgumentParser(description="Evaluate Recovered Queries")
    parser.add_argument("--input", default="agent/searching_results/e2e_run_20260125_130247/recovered_queries_test_200.jsonl", help="Input JSONL")
    parser.add_argument("--output", default="evaluation_results_recovered_test.csv", help="Output CSV")
    parser.add_argument("--workers", type=int, default=4, help="Workers")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of cases")
    parser.add_argument("--random", action="store_true", help="Randomly sample cases")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        log.error(f"Input not found: {args.input}")
        return

    # Load Queries
    tasks = []
    run_timestamp = time.strftime("%Y%m%d_%H%M%S")
    os.environ["LANGCHAIN_PROJECT"] = f"QG Test Downstream Agent Run - {run_timestamp}"
    base_data_dir = "/data/chen/e2e_searching_results" # Use data partition
    run_dir = os.path.abspath(os.path.join(base_data_dir, f"recovered_eval_run_{run_timestamp}"))
    os.makedirs(run_dir, exist_ok=True)
    
    log.info(f"Loading queries from {args.input}...")
    
    # Manager for GPU Queue
    manager = mp.Manager()
    gpu_queue = manager.Queue()
    n_gpus = torch.cuda.device_count()
    if n_gpus == 0: n_gpus = 1
    for i in range(args.workers):
        gpu_queue.put(i % n_gpus)

    # --- RESUME LOGIC ---
    processed_chemicals = set()
    if os.path.exists(args.output):
        try:
            existing_df = pd.read_csv(args.output)
            if "chemical_name" in existing_df.columns:
                processed_chemicals = set(existing_df["chemical_name"].astype(str))
            log.info(f"Resuming: Found {len(processed_chemicals)} already processed chemicals in {args.output}")
        except Exception as e:
            log.warning(f"Could not read existing results file: {e}. Starting fresh.")

    with open(args.input, 'r') as f:
        for line in f:
            if not line.strip(): continue
            try:
                data = json.loads(line)
                query = data.get("query")
                if query:
                    if not isinstance(query, str):
                        # Attempt to extract if it's a dict like {"role": "user", "content": "..."}
                        if isinstance(query, dict) and "content" in query:
                            query = query["content"]
                        else:
                            # log.warning(f"Skipping non-string query type: {type(query)}")
                            continue
                            
                    chem_name = extract_chemical_name(query)
                    
                    # SKIP IF ALREADY DONE
                    if chem_name in processed_chemicals:
                        continue
                        
                    tasks.append((query, chem_name, run_dir, gpu_queue))
            except json.JSONDecodeError:
                pass
                
    log.info(f"Found {len(tasks)} PENDING queries to process (skipped {len(processed_chemicals)}).")
    

    # ... (existing code)
    if not tasks:
        log.info("All tasks completed! Nothing to do.")
    else: # Indent the processing block or just proceed if tasks exist
        pass

    # LIMIT / RANDOM AFTER Filtering
    if args.random:
        import random
        random.shuffle(tasks)
        log.info("Tasks shuffled.")
    
    if args.limit > 0 and len(tasks) > args.limit:
        tasks = tasks[:args.limit]
        log.info(f"Limited tasks to {args.limit}.")

    results = []
    processed_count = 0
    
    log.info(f"Starting pool with {args.workers} workers for {len(tasks)} tasks...")
    
    # Initialize CSV header if file doesn't exist
    if not os.path.exists(args.output):
        pd.DataFrame(columns=["chemical_name", "query", "status", "agent_verdict", "normalized_prediction", "session_dir", "tokens_used", "cost_usd", "last_researcher_json", "last_critique_json"]).to_csv(args.output, index=False)
    
    with mp.Pool(processes=args.workers, maxtasksperchild=1) as pool:
        for res in pool.imap_unordered(process_one_safe, tasks):
            processed_count += 1
            log.info(f"[{processed_count}/{len(tasks)}] {res['chemical_name']}: {res['normalized_prediction']}")
            
            # Incremental Append
            pd.DataFrame([res]).to_csv(args.output, mode='a', header=False, index=False)

    log.info(f"Done. Appended results to {args.output}")
    log.info(f"Done. Saved to {args.output}")

    # --- PLOT GENERATION ---
    try:
        import matplotlib.pyplot as plt
        log.info("Generating plot...")
        df = pd.read_csv(args.output)
        if not df.empty and "normalized_prediction" in df.columns:
            plt.figure(figsize=(10, 6))
            counts = df['normalized_prediction'].value_counts()
            counts.plot(kind='bar', color='skyblue')
            plt.title(f'Distribution of Normalized Predictions (N={len(df)})')
            plt.xlabel('Prediction')
            plt.ylabel('Count')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            
            plot_path = os.path.splitext(args.output)[0] + '.png'
            plt.savefig(plot_path)
            log.info(f"Plot saved to {plot_path}")
            print(f"Plot generated at: {plot_path}")
    except Exception as e:
        log.error(f"Failed to generate plot: {e}")

if __name__ == "__main__":
    main()
