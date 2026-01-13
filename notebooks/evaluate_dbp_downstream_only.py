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
# --- IMPORTS ---
try:
    from e2e_agent import (
        down_app, 
        determine_final_claim, 
        FullTextJournalSearchTool, 
        HumanMessage
    )
    print("Successfully imported e2e_agent components.")
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import e2e_agent. Make sure e2e_agent.py is in key path. {e}")
    sys.exit(1)

load_dotenv()

def evaluate_compound(compound_name: str, base_results_dir: str = "../searching_results") -> dict:
    """
    Run downstream agent verification for a single compound.
    """
    # -----------------------------
    if not isinstance(compound_name, str) or not compound_name.strip():
        return {
            "input_compound": str(compound_name),
            "agent_verdict": "Skipped (Empty)",
            "normalized_prediction": "N/A",
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
        "by the reaction of a disinfectant with organic and inorganic matter present in water. "
        "To be considered 'experimentally confirmed', there must be clear evidence from a peer-reviewed "
        "study demonstrating its formation during a disinfection process."
    )
    
    # Query
    query_text = (
        f"According to the definition provided below, decide whether '{compound_name}' is a confirmed DBP:\n"
        f"\"{definition}\"\n\n"
        f"Is there peer-reviewed evidence that '{compound_name}' is formed during water disinfection? "
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
    
    config = {"configurable": {"thread_id": session_id}}
    
    try:
        # Invoke downstream app directly
        final_state = down_app.invoke(initial_state, config=config)
        claim = determine_final_claim(final_state["messages"])
    except Exception as e:
        print(f" [Error: {e}]")
        claim = "Error"
    
    # Normalize
    predicted = "Unclear"
    c_low = str(claim).lower()
    if "not confirmed" in c_low:
        predicted = "No"
    elif "confirmed" in c_low:
        predicted = "Yes"
        
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
    compound, original_row, run_dir = args_tuple
    try:
        # Invoke directly
        res = evaluate_compound(compound, base_results_dir=run_dir)
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

def main():
    # Use 'spawn' for safe PyTorch/CUDA multiprocessing
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass

    parser = argparse.ArgumentParser(description="Run Evaluation on DBPs (Parallel)")
    parser.add_argument("--input", default="/home/chen/GNPS_SIM/agent/db_form_agent_system/notebooks/dbp_gemini_flash_2_5_results.xlsx", help="Input Excel file")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of rows (0 for all)")
    parser.add_argument("--output", default="evaluation_results_new.csv", help="Output CSV")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}")
        return

    print(f"Loading {args.input}...")
    df = pd.read_excel(args.input)
    
    if 'IUPAC name' not in df.columns:
        print(f"Column 'IUPAC name' not found. Columns: {df.columns.tolist()}")
        return
        
    print(f"Total rows: {len(df)}")
    
    if args.limit > 0:
        df = df.head(args.limit)
        print(f"Limiting to first {args.limit} rows.")
    results = []
    processed_compounds = set()
    
    # Check for existing output file to RESUME
    output_file = args.output
    
    # Resume capability
    start_index = 0
    if os.path.exists(output_file):
        try:
            existing_df = pd.read_csv(output_file)
            if "input_compound" in existing_df.columns: # Assuming 'input_compound' is the column for compound names in the output
                processed_compounds = set(existing_df["input_compound"].unique())
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
    
    # We need a map from future to input data to reconstruct rows
    # Pre-calculate the full list of inputs with their metadata
    tasks = []
    for _, row in df.iterrows():
        input_compound = row['IUPAC name']
        # Pass Tuple: (Compound, RowDict, RunDir)
        tasks.append((input_compound, row.to_dict(), run_dir))

    # Use ProcessPoolExecutor for dynamic scheduling (True Parallelism)
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks at once; executor handles the queue
        # Note: We submit 'process_one_safe' which is TOP LEVEL.
        future_to_compound = {
            executor.submit(process_one_safe, task): task[0] 
            for task in tasks
        }
        
        for future in as_completed(future_to_compound):
            compound_name = future_to_compound[future]
            try:
                result_row = future.result()
                results.append(result_row)
                processed += 1
                
                # Print status
                print(f"[{processed}/{len(df)}] {result_row['input_compound']}: {result_row['agent_verdict']}")
                
                # Incremental save (save after every item strictly)
                pd.DataFrame(results).to_csv(args.output, index=False)
                
            except Exception as exc:
                print(f"Generated an exception for {compound_name}: {exc}")

    # Final save
    pd.DataFrame(results).to_csv(args.output, index=False)
    print(f"\nDone. Results saved to {args.output}")

if __name__ == "__main__":
    main()
