import sys
import os
import pandas as pd
import uuid
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv
# import torch (Moved to main)
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
# from concurrent.futures import ThreadPoolExecutor, as_completed # Disabled
from threading import Lock

# --- SETUP PATHS ---
current_dir = os.getcwd()

# Ensure we can import from code/
code_dir = os.path.abspath(os.path.join(current_dir, '../code'))
if code_dir not in sys.path:
    sys.path.append(code_dir)

# Ensure we can import e2e_agent from current dir
if current_dir not in sys.path:
    sys.path.append(current_dir)

# --- IMPORTS ---
# --- IMPORTS (Moved to local scope for Multi-GPU safety) ---
# try:
#     from e2e_agent import (
#         down_app, 
#         determine_final_claim, 
#         FullTextJournalSearchTool, 
#         HumanMessage
#     )
#     print("Successfully imported e2e_agent components.")
# except ImportError as e:
#     print(f"CRITICAL ERROR: Could not import e2e_agent. Make sure e2e_agent.py is in key path. {e}")
#     sys.exit(1)

load_dotenv()

def evaluate_compound(compound_name: str, base_results_dir: str = "../searching_results") -> dict:
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

    session_id = f"eval_{uuid.uuid4().hex[:8]}"
    session_dir = os.path.join(base_results_dir, f"dbp_eval_{session_id}")
    os.makedirs(session_dir, exist_ok=True)
    
    # Configure Tool Session - Thread Safe due to ContextVar usage in searching_tool.py
    FullTextJournalSearchTool.set_session_dir(session_dir)
    
    # Strict Definition
    definition = (
        "A disinfection byproduct (DBP) is a chemical compound that is formed incidentally "
        "by the reaction of a disinfectant with organic and inorganic matter present in water."
    )
    
    # Query
    query_text = (
        f"According to the definition provided below, decide whether '{compound_name}' is a confirmed DBP:\n"
        f"\"{definition}\"\n\n"
        "Answer 'Confirmed DBP' or 'Not Confirmed DBP'."
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
    
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": int(os.environ.get("AGENT_RECURSION_LIMIT", 25))
    }
    
    try:
        # Invoke downstream app directly
        final_state = down_app.invoke(initial_state, config=config)
        claim = determine_final_claim(final_state["messages"])
    except Exception as e:
        print(f" [Error: {e}]")
        claim = "Error"
    
    # ROBUST VERDICT EXTRACTION
    predicted = str(claim) 
    
    # 1. Try treating it as a JSON blob
    try:
        if "{" in predicted:
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

    # 2. If it still looks like a JSON string or wasn't parsed, try regex
    # This catches: "claim": "Confirmed" buried in text
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


# Function must be top-level for ProcessPoolExecutor with spawn
def process_one(task_data):
    # We need to recreate the runnable or invoke the function directly?
    # eval_runnable is local to main.
    # We can't pass eval_runnable if it's a lambda/partial that captures local vars.
    # We should just call evaluate_compound directly.
    compound, original_row = task_data
    try:
        # Re-bind session dir? No, evaluate_compound handles it?
        # evaluate_compound takes (name, base_results_dir).
        # We need to pass base_results_dir.
        # But task_data only has (compound, row_dict).
        # We need to pass base_results_dir in the task tuple.
        pass
    except Exception:
        pass
    # Placeholder logic - see below for actual replacement
    return {}

# Actually, we need to restructure how we pass args.
# Let's fix process_one to take a tuple including output_dir.

def process_one_safe(args_tuple):
    # Unpack args (now includes gpu_queue)
    if len(args_tuple) == 4:
        compound, original_row, run_dir, gpu_queue = args_tuple
    else:
        # Fallback for old calls if any
        compound, original_row, run_dir = args_tuple
        gpu_queue = None

    # Setup GPU for this single task (since process will die after)
    gpu_id = None
    if gpu_queue:
        try:
            # Get ID with timeout (should be instant if queue size == workers)
            gpu_id = gpu_queue.get(timeout=10)
        except Exception:
            gpu_id = None
            
    # Initialize GPU
    try:
        from e2e_agent import setup_gpu_worker
        setup_gpu_worker(gpu_id)
    except ImportError:
        pass

    try:
        # Invoke directly with token/cost tracking
        from langchain_community.callbacks import get_openai_callback
        with get_openai_callback() as cb:
            res = evaluate_compound(compound, base_results_dir=run_dir)
        # Add token and cost info to the result dict
        res["tokens_used"] = cb.total_tokens
        res["cost_usd"] = round(cb.total_cost, 6)
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
        # CRITICAL: Return the GPU ID to the queue for the next worker
        if gpu_queue and gpu_id is not None:
             gpu_queue.put(gpu_id)

def main():
    # Use 'spawn' for safe PyTorch/CUDA multiprocessing
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass
    
    import torch # Delayed import

    parser = argparse.ArgumentParser(description="Run Evaluation on DBPs (Parallel)")
    parser.add_argument("--input", default="/home/chen/GNPS_SIM/agent/db_form_agent_system/notebooks/dbp_gemini_flash_2_5_results.xlsx", help="Input Excel file")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of rows (0 for all)")
    parser.add_argument("--output", default="evaluation_results_new.csv", help="Output CSV")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}")
        return

    # --- TARGETED TESTING (DISABLED - FULL RUN) ---
    # print("Running TARGETED TEST on known difficult cases...")
    # target_compounds = ["4-Bromophenol", "Iodoacetonitrile", "2,4,6-Tribromo-1,4-benzoquinone", "Chloroform", "Hexanal"]
    # df = pd.DataFrame({'IUPAC name': target_compounds})
    # ---------------------------------------
    
    # --- FULL DATASET LOADING ---
    print(f"Loading {args.input}...")
    if args.input.endswith(".csv"):
        df = pd.read_csv(args.input)
    else:
        df = pd.read_excel(args.input)
    
    if 'IUPAC name' not in df.columns:
        print(f"Column 'IUPAC name' not found. Columns: {df.columns.tolist()}")
        return
        
    print(f"Total rows: {len(df)}")
    
    if args.limit > 0:
        df = df.head(args.limit)
        print(f"Limiting to first {args.limit} rows.")
    # ----------------------------

    # Set LangSmith Project
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    time_str = time.strftime("%Y%m%d_%H%M%S")   
    os.environ["LANGCHAIN_PROJECT"] = f"SOTA_VERIFICATION_RUN_{time_str}"
    results = []
    processed_compounds = set()
    
    # Check for existing output file to RESUME
    output_file = args.output
    
    # Resume capability
    start_index = 0
    if os.path.exists(output_file):
        try:
            existing_df = pd.read_csv(output_file)
            if "IUPAC name" in existing_df.columns: # Found previously processed output
                processed_compounds = set(existing_df["IUPAC name"].unique())
                results = existing_df.to_dict('records')
                print(f"Resuming from {output_file}. Found {len(processed_compounds)} already processed.")
        except Exception as e:
            print(f"Warning: Could not read existing output file: {e}")

    # Filter df to skip already processed
    original_count = len(df)
    df = df[~df['IUPAC name'].isin(processed_compounds)]
    print(f"Skipping {len(processed_compounds)} items. Remaining to process: {len(df)}")
    
    if len(df) == 0:
        print("All items processed. Exiting.")
        return

    print(f"\nStarting Parallel Evaluation Loop with {args.workers} workers...")
    
    # Create a timestamped run directory
    run_timestamp = time.strftime("%Y%m%d_%H%M%S")
    # Redirect to /data partition to solve disk space issues
    # run_dir = os.path.abspath(os.path.join(current_dir, "searching_results", f"dbp_eval_run_{run_timestamp}"))
    base_data_dir = "/data/chen/e2e_searching_results"
    run_dir = os.path.abspath(os.path.join(base_data_dir, f"dbp_eval_run_{run_timestamp}"))
    os.makedirs(run_dir, exist_ok=True)
    print(f"Results will be stored in: {run_dir}")

    print("\nStarting Dynamic Queue Evaluation...")
    processed = 0
    
    # Create a Manager Queue for GPU distribution
    manager = mp.Manager()
    gpu_queue = manager.Queue()
    n_gpus = torch.cuda.device_count()
    print(f"\n[DEBUG] Main Process detected {n_gpus} GPUs via torch.cuda.device_count()")
    if n_gpus == 0: 
        print("[DEBUG] Warning: No GPUs detected. Fallback to n_gpus=1 (CPU/Mock).")
        n_gpus = 1
    
    # Populate queue with round-robin IDs [0, 1, 0, 1, ...]
    print(f"[DEBUG] Populating GPU Queue for {args.workers} workers...")
    for i in range(args.workers):
        gid = i % n_gpus
        gpu_queue.put(gid)
        print(f"[DEBUG] Queue Item {i}: {gid}")

    # We need a map from future to input data to reconstruct rows
    # Pre-calculate the full list of inputs with their metadata
    tasks = []
    for _, row in df.iterrows():
        input_compound = row['IUPAC name']
        # Pass Tuple: (Compound, RowDict, RunDir, GPU_Queue)
        tasks.append((input_compound, row.to_dict(), run_dir, gpu_queue))

    # Use multiprocessing.Pool with maxtasksperchild=1 to prevent memory accumulation (OOM)
    # This forces the worker process to exit and restart after processing exactly one item, 
    # ensuring all memory (GPU context, global caches) is released.
    print(f"\n[System] Initialization complete. Starting Pool with maxtasksperchild=1 for stability.")
    
    try:
        with mp.Pool(processes=args.workers, maxtasksperchild=1) as pool:
            # imap_unordered yields results as soon as they are ready
            for result_row in pool.imap_unordered(process_one_safe, tasks):
                try:
                    results.append(result_row)
                    processed += 1
                    
                    # Print status
                    comp_name = result_row.get('input_compound', 'Unknown')
                    verdict = result_row.get('agent_verdict', 'Error')
                    print(f"[{processed}/{len(df)}] {comp_name}: {verdict}")
                    
                    # Incremental save (Robust against crashes)
                    save_df = pd.DataFrame(results)
                    # Filter columns to keep IUPAC name, agent_verdict, and normalized_prediction
                    keep_cols = [c for c in ['IUPAC name', 'agent_verdict', 'normalized_prediction'] if c in save_df.columns]
                    if keep_cols:
                         save_df = save_df[keep_cols]
                    save_df.to_csv(args.output, index=False)
                    
                except Exception as exc:
                    print(f"Error handling result in main loop: {exc}")
    except Exception as e:
        print(f"Critical Pool Error: {e}")
        # Save whatever we have
        save_df = pd.DataFrame(results)
        keep_cols = [c for c in ['IUPAC name', 'agent_verdict', 'normalized_prediction'] if c in save_df.columns]
        if keep_cols:
            save_df = save_df[keep_cols]
        save_df.to_csv(args.output, index=False)

    # Final save
    save_df = pd.DataFrame(results)
    keep_cols = [c for c in ['IUPAC name', 'agent_verdict', 'normalized_prediction'] if c in save_df.columns]
    if keep_cols:
        save_df = save_df[keep_cols]
    save_df.to_csv(args.output, index=False)
    print(f"\nDone. Results saved to {args.output}")

if __name__ == "__main__":
    main()
