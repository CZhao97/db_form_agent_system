
import sys
import os
import json
import random
import time
import pandas as pd
import pathlib
import logging
from typing import List, Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.callbacks import get_openai_callback

# Add code/ path
sys.path.append(os.path.join(os.path.dirname(__file__), '../code'))

# Import e2e_agent components
from e2e_agent import (
    down_app, 
    research_model, 
    down_stream_tools, 
    LITERATURE_PROMPT_PATH, 
    researcher_agent_executor,
    FullTextJournalSearchTool,
    FullTextIndexTool,
    FullTextQueryTool,
    CompoundDatabaseTool
)
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

# Disable noisy logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("e2e_agent").setLevel(logging.WARNING)

RESULTS_FILE = "benchmark_results.csv"
SUBSET_SIZE = 20
BASE_DIR = "/home/chen/GNPS_SIM/agent/db_form_agent_system"

def load_subset_compounds(n=20) -> List[Dict]:
    """Load a random N compounds from the source data."""
    # Assuming input data is in current dir or known path. Using the evaluation output as source of names if input not found?
    # Better: Use the input file `eval_input_list.csv` or similar if exists.
    # Fallback: Use `evaluation_results_new.csv` and pick randoms.
    try:
        if os.path.exists("evaluation_results_new.csv"):
            df = pd.read_csv("evaluation_results_new.csv")
        elif os.path.exists("evaluation_results_corrupt_backup.csv"):
            print("[Info] Loading input from backup file.")
            df = pd.read_csv("evaluation_results_corrupt_backup.csv")
        else:
            # Fallback to the original input source
            df = pd.read_excel("dbp_gemini_flash_2_5_results.xlsx")
    except Exception as e:
        print(f"[Warn] Could not load input: {e}")
        return []
        
    if "IUPAC name" in df.columns:
        valid_df = df[df["IUPAC name"].notnull()]
        sample = valid_df.sample(n=min(n, len(valid_df)), random_state=42)
        return sample.to_dict('records')
    return []

def get_modified_researcher(k: int):
    """
    Rebuilds the researcher agent executor with:
    1. A Prompt that specifies k={k}
    2. A FullTextQueryTool hardcoded to k={k}
    """
    # 1. Patch Tools
    new_tools = []
    for t in down_stream_tools:
        if isinstance(t, FullTextQueryTool):
            # Create a NEW instance with override
            # We must pass the directory if needed, or rely on update logic
            new_t = FullTextQueryTool(results_base_dir=t.results_base_dir, k=k)
            new_tools.append(new_t)
        else:
            new_tools.append(t)
            
    # 2. Patch Prompt
    raw_prompt = LITERATURE_PROMPT_PATH.read_text(encoding="utf-8")
    # Replace the instruction "k: 25" with "k: {k}"
    # Regex might be safer but string replace is fine if text is stable
    # The prompt has: `Inputs: {"run_path": "...", "query": str, "k": 25}`
    patched_prompt_text = raw_prompt.replace('"k": 25', f'"k": {k}')
    # Also look for valid ranges if any
    
    sys_msg = SystemMessage(content=patched_prompt_text)
    
    # 3. Create Agent
    memory = MemorySaver()
    new_executor = create_react_agent(
        research_model, 
        new_tools, 
        prompt=sys_msg,
        checkpointer=memory
    )
    return new_executor

def run_single_eval(compound_row, k, max_iterations):
    """Run verification for one compound with specific params."""
    
    # We need to PATCH the global 'researcher_agent_executor' in e2e_agent module
    # Because 'down_app' calls 'researcher_node', which imports it.
    # We can do this by modifying the module attribute.
    import e2e_agent
    
    # Create the specialized agent
    special_agent = get_modified_researcher(k)
    
    # Context Manager to swap the agent
    original_agent = e2e_agent.researcher_agent_executor
    e2e_agent.researcher_agent_executor = special_agent
    
    try:
        # Prepare Input
        # We need to create a directory or re-use one?
        # Ideally benchmarks should be repeatable.
        # Let's make a temp session dir.
        clean_name = "".join(x for x in compound_row.get("IUPAC name", "Unknown") if x.isalnum())[:30]
        ts = int(time.time())
        session_dir = os.path.join(BASE_DIR, "benchmark_runs", f"{clean_name}_{ts}_k{k}_d{max_iterations}")
        os.makedirs(session_dir, exist_ok=True)
        
        # We assume the compound has been searched before?
        # If not, the agent will try to search.
        # To strictly benchmark verification cost, ideally we have the docs already.
        # But for E2E benchmark, we allow it to search (which dominates time).
        # OR we cp data from previous run? 
        # Simulating "New Search" is fairer for "E2E Cost".
        
        # Input State
        query = f"Does {compound_row.get('IUPAC name')} form NDMA?"
        
        initial_state = {
            'messages': [HumanMessage(content=query)],
            'original_query': query,
            'search_session_dir': session_dir,
            'stop_history': [],
            'claim_history': [],
            'confidence_history': [],
            'consecutive_no_new_evidence': 0,
            'consecutive_tool_unavailable': 0,
            'last_researcher_json': None,
            'last_critique_json': None,
        }
        
        config = {
            "configurable": {"thread_id": f"bench_{ts}"},
            "recursion_limit": max_iterations * 2 + 10 # Allow for overhead
        }
        
        start_time = time.time()
        
        # TRACK TOKENS
        with get_openai_callback() as cb:
            final_state = down_app.invoke(initial_state, config=config)
            
        duration = time.time() - start_time
        
        # Extract Result
        final_hist = final_state.get("stop_history", [])
        last_entry = final_hist[-1] if final_hist else {}
        
        result = {
            "compound": compound_row.get("IUPAC name"),
            "k_param": k,
            "depth_param": max_iterations,
            "duration_sec": round(duration, 2),
            "total_tokens": cb.total_tokens,
            "input_tokens": cb.prompt_tokens,
            "output_tokens": cb.completion_tokens,
            "cost_usd": round(cb.total_cost, 4),
            "final_verdict": last_entry.get("claim", "Unclear"),
            "confidence": last_entry.get("confidence_score", 0.0),
            "stop_reason": last_entry.get("stop_reason", "Limit Reached")
        }
        return result
        
    except Exception as e:
        print(f"Error for {compound_row.get('IUPAC name')}: {e}")
        return {
            "compound": compound_row.get("IUPAC name"),
            "k_param": k,
            "depth_param": max_iterations,
            "error": str(e)
        }
    finally:
        # Restore
        e2e_agent.researcher_agent_executor = original_agent

def main():
    print("Starting Benchmark...")
    compounds = load_subset_compounds(SUBSET_SIZE)
    if not compounds:
        print("No input compounds found!")
        return
        
    print(f"Loaded {len(compounds)} compounds for testing.")
    
    # Experiments
    # Exp 1: Vary k (Fixed Depth=5)
    k_levels = [5, 10, 25, 50]
    fixed_depth = 5
    
    # Exp 2: Vary Depth (Fixed k=25)
    # We can skip the case already covered above (k=25, d=5)
    depth_levels = [3, 10]
    
    results = []
    
    # 1. K-Experiment
    for k in k_levels:
        print(f"\n--- Running k={k} (Depth={fixed_depth}) ---")
        for i, comp in enumerate(compounds):
            print(f"[{i+1}/{len(compounds)}] {comp.get('IUPAC name')}...", end="", flush=True)
            res = run_single_eval(comp, k, fixed_depth)
            results.append(res)
            print(f" Done ({res.get('duration_sec', 'Err')}s)")
            
            # Save incrementally
            pd.DataFrame(results).to_csv(RESULTS_FILE, index=False)

    # 2. Depth-Experiment
    fixed_k = 25
    for d in depth_levels:
        print(f"\n--- Running Depth={d} (k={fixed_k}) ---")
        for i, comp in enumerate(compounds):
            print(f"[{i+1}/{len(compounds)}] {comp.get('IUPAC name')}...", end="", flush=True)
            res = run_single_eval(comp, fixed_k, d)
            results.append(res)
            print(f" Done ({res.get('duration_sec', 'Err')}s)")
            pd.DataFrame(results).to_csv(RESULTS_FILE, index=False)
            
    print(f"\nBenchmark Complete. Results saved to {RESULTS_FILE}")

if __name__ == "__main__":
    main()
