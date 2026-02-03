
import sys
import os
import pandas as pd
import uuid
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from threading import Lock

# --- SETUP PATHS ---
current_dir = os.getcwd()

# Ensure we can import from code/
code_dir = os.path.abspath(os.path.join(current_dir, 'agent/code'))
if code_dir not in sys.path:
    sys.path.append(code_dir)

# Ensure we can import e2e_agent from notebooks dir
notebooks_dir = os.path.abspath(os.path.join(current_dir, 'notebooks'))
if notebooks_dir not in sys.path:
    sys.path.append(notebooks_dir)
# Also add current dir just in case
if current_dir not in sys.path:
    sys.path.append(current_dir)

load_dotenv()

def evaluate_compound(compound_name: str, base_results_dir: str = "agent/searching_results") -> dict:
    """
    Run downstream agent verification for a single compound.
    """
    if not isinstance(compound_name, str) or not compound_name.strip():
        return {
            "input_compound": str(compound_name),
            "agent_verdict": "Skipped (Empty)",
            "normalized_prediction": "N/A",
            "session_dir": ""
        }
        
    # Lazy Import to ensure GPU env vars are set BEFORE loading torch/models
    try:
        from e2e_agent import (
            down_app, 
            determine_final_claim, 
            FullTextJournalSearchTool, 
            HumanMessage
        )
    except ImportError as e:
        return {
             "input_compound": compound_name,
             "agent_verdict": "Error",
             "normalized_prediction": f"Import Error: {e}",
             "session_dir": ""
        }

    session_id = f"eval_blood_{uuid.uuid4().hex[:8]}"
    session_dir = os.path.join(base_results_dir, f"blood_eval_{session_id}")
    os.makedirs(session_dir, exist_ok=True)
    
    # Configure Tool Session
    FullTextJournalSearchTool.set_session_dir(session_dir)
    
    # Definition for Blood Exposome
    definition = (
        "The blood exposome consists of chemicals that have been experimentally detected "
        "and identified in human blood samples (serum, plasma, or whole blood)."
    )
    
    # Query
    query_text = (
        f"According to the definition provided below, decide whether '{compound_name}' is a confirmed member of the human blood exposome:\n"
        f"\"{definition}\"\n\n"
        f"Based on the peer-reviewed literature, has '{compound_name}' been detected in human blood?"
    )
    
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
    
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 30}
    
    try:
        # Invoke downstream app directly
        final_state = down_app.invoke(initial_state, config=config)
        claim = determine_final_claim(final_state["messages"])
    except Exception as e:
        claim = "Error"
        print(f"Error invoking agent for {compound_name}: {e}")
    
    # ROBUST VERDICT EXTRACTION
    predicted = str(claim) 
    
    # 1. Try treating it as a JSON blob
    try:
        if "{" in predicted:
            import json
            # Extract purely the JSON part
            start = predicted.find("{")
            end = predicted.rfind("}") + 1
            json_str = predicted[start:end]
            data = json.loads(json_str)
            
            # Check nested "verdict_statement" -> "claim"
            if isinstance(data, dict):
                vs = data.get("verdict_statement")
                if isinstance(vs, dict) and "claim" in vs:
                     predicted = vs["claim"]
                elif "claim" in data:
                     predicted = data["claim"]
    except:
         pass

    # 2. Regex Fallback
    if "{" in str(predicted) or len(str(predicted)) > 50:
         import re
         m = re.search(r'"claim"\s*:\s*"([^"]+)"', str(claim))
         if m:
             predicted = m.group(1).strip()
    
    return {
        "input_compound": compound_name,
        "agent_verdict": claim,
        "normalized_prediction": predicted,
        "session_dir": session_dir
    }

def process_one_safe(args_tuple):
    # Unpack args (now includes gpu_queue)
    if len(args_tuple) == 4:
        compound, original_row, run_dir, gpu_queue = args_tuple
    else:
        compound, original_row, run_dir = args_tuple
        gpu_queue = None

    # Setup GPU
    gpu_id = None
    if gpu_queue:
        try:
            gpu_id = gpu_queue.get(timeout=10)
        except Exception:
            gpu_id = None
            
    # Initialize GPU
    try:
        # sys.path hack to find e2e_agent if running from scripts dir
        sys.path.append(os.path.join(os.getcwd(), 'notebooks'))
        from e2e_agent import setup_gpu_worker
        setup_gpu_worker(gpu_id)
    except ImportError:
        pass

    try:
        # Invoke directly with token/cost tracking
        from langchain_community.callbacks import get_openai_callback
        with get_openai_callback() as cb:
            res = evaluate_compound(compound, base_results_dir=run_dir)
        
        # Add token and cost info
        res["tokens_used"] = cb.total_tokens
        res["cost_usd"] = round(cb.total_cost, 6)
        
        # Merge with original row data (e.g. BloodPaperCount)
        original_row.update(res)
        return original_row
    
    except Exception as e:
        print(f"Error processing {compound}: {e}")
        original_row.update({
            "input_compound": compound,
            "agent_verdict": "Error",
            "normalized_prediction": f"Error: {str(e)}",
            "session_dir": ""
        })
        return original_row
        
    finally:
        if gpu_queue and gpu_id is not None:
             gpu_queue.put(gpu_id)

def main():
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass
    
    import torch 

    parser = argparse.ArgumentParser(description="Run Evaluation on Blood Exposome (Parallel)")
    parser.add_argument("--input", default="blood_exposome_chemicals_july_2023.csv", help="Input CSV file")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of rows (0 for all)")
    parser.add_argument("--output", default="evaluation_results_blood.csv", help="Output CSV")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    
    parser.add_argument("--random", action="store_true", help="Randomly sample rows")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}")
        return

    # --- LOAD DATA ---
    print(f"Loading {args.input}...")
    df = pd.read_csv(args.input)
    
    # Use "Title" column for chemical name
    if 'Title' not in df.columns:
        print(f"Column 'Title' not found. Columns: {df.columns.tolist()}")
        return
    
    # Optional: Fill NaN titles? drop them?
    df = df.dropna(subset=['Title'])
    
    print(f"Total rows: {len(df)}")
    
    if args.limit > 0:
        if args.random:
            print(f"Randomly sampling {args.limit} rows with seed {args.seed}...")
            if len(df) > args.limit:
                df = df.sample(n=args.limit, random_state=args.seed)
            else:
                print(f"Requested limit {args.limit} >= total rows {len(df)}. Using all rows.")
        else:
            df = df.head(args.limit)
            print(f"Limiting to first {args.limit} rows.")

    # --- RESUME LOGIC ---
    processed_compounds = set()
    if os.path.exists(args.output):
        try:
            existing_df = pd.read_csv(args.output)
            if "input_compound" in existing_df.columns:
                processed_compounds = set(existing_df["input_compound"].unique())
                print(f"Resuming from {args.output}. Found {len(processed_compounds)} already processed.")
        except Exception as e:
            print(f"Warning: Could not read existing output file: {e}")

    # Create run dir
    run_timestamp = time.strftime("%Y%m%d_%H%M%S")
    os.environ["LANGCHAIN_PROJECT"] = f"Blood Eval Run - {run_timestamp}"
    base_data_dir = "/data/chen/e2e_searching_results" # Use data partition
    run_dir = os.path.abspath(os.path.join(base_data_dir, f"blood_eval_run_{run_timestamp}"))
    os.makedirs(run_dir, exist_ok=True)
    print(f"Results will be stored in: {run_dir}")

    # Prepare Queue
    manager = mp.Manager()
    gpu_queue = manager.Queue()
    n_gpus = torch.cuda.device_count()
    if n_gpus == 0: n_gpus = 1
    for i in range(args.workers):
        gpu_queue.put(i % n_gpus)

    # Prepare Tasks
    tasks = []
    skipped_count = 0
    for _, row in df.iterrows():
        input_compound = row['Title']
        
        if input_compound in processed_compounds:
            skipped_count += 1
            continue
            
        tasks.append((input_compound, row.to_dict(), run_dir, gpu_queue))
        
    print(f"Skipped {skipped_count} items. Queued {len(tasks)} items.")
    
    if not tasks:
        print("Nothing to do.")
        return

    # Initialize Output Header if new
    if not os.path.exists(args.output):
        # We don't know exact columns yet, but we know the basics.
        # We'll let pandas handle it on the first write or just write in loop.
        # Actually better to just write the first result with header, then subsequent without.
        pass

    processed_count = 0
    print(f"Starting Pool with {args.workers} workers...")
    
    with mp.Pool(processes=args.workers, maxtasksperchild=1) as pool:
        for res in pool.imap_unordered(process_one_safe, tasks):
            processed_count += 1
            
            name = res.get('Title', 'Unknown')
            verdict = res.get('normalized_prediction', 'N/A')
            print(f"[{processed_count}/{len(tasks)}] {name}: {verdict}")
            
            # Incremental Append
            res_df = pd.DataFrame([res])
            # Filter columns to keep file size manageable? 
            # Or keep all from input + new fields (verdict, cost, etc)
            
            # Writing mode
            write_header = not os.path.exists(args.output)
            res_df.to_csv(args.output, mode='a', header=write_header, index=False)

    print(f"Done. Saved to {args.output}")

if __name__ == "__main__":
    main()
