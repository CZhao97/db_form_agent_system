
print("DEBUG: Script Started", flush=True)
import sys
import os
import time

# MOCK SQLITE (CRITICAL: Must be first)
from unittest.mock import MagicMock
sys.modules["sqlite3"] = MagicMock()
sys.modules["sqlite3.dbapi2"] = MagicMock()

print("Imports starting...", flush=True)
import pandas as pd
from langsmith import Client
from dotenv import load_dotenv

load_dotenv()
client = Client()
print("Client ready.", flush=True)

RUN_ID = "d24c9334-5b8c-4c98-b032-b53f6f164314"

def analyze():
    print(f"Fetching run {RUN_ID}...", flush=True)
    try:
        run = client.read_run(RUN_ID)
        print(f"Run Name: {run.name}", flush=True)
        print(f"Status: {run.status}", flush=True)
        
        # Analyze Input Query
        if run.inputs:
            print("\n--- Root Inputs ---", flush=True)
            # Check for messages
            msgs = run.inputs.get("messages", [])
            if msgs:
                if isinstance(msgs, list) and len(msgs) > 0:
                    last_msg = msgs[-1]
                    content = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
                    print(f"User Query: {content}", flush=True)
                else:
                    print(f"Messages raw: {str(msgs)[:200]}", flush=True)
            
        print("\nFetching Trace Runs...", flush=True)
        trace_runs = list(client.list_runs(trace_id=run.trace_id))
        print(f"Found {len(trace_runs)} items in trace.", flush=True)
        
        # Filter for key tools
        search_calls = [r for r in trace_runs if r.name == "fulltext_journal_search"]
        ner_calls = [r for r in trace_runs if r.name == "chemical_ner"]
        inspect_calls = [r for r in trace_runs if r.name == "inspect_search_results"]
        
        print(f"\n--- Search Tool Calls ({len(search_calls)}) ---", flush=True)
        for i, r in enumerate(search_calls):
            print(f"Call {i+1} Status: {r.status}", flush=True)
            print(f"  Inputs: {r.inputs}", flush=True)
            # Summarize output
            out = str(r.outputs)
            if "total_results" in out: 
                print(f"  Results: Yes (Length {len(out)})", flush=True)
            else:
                print(f"  Results: {out[:200]}...", flush=True)
                
        print(f"\n--- Inspect Tool Calls ({len(inspect_calls)}) ---", flush=True)
        for i, r in enumerate(inspect_calls):
            print(f"Call {i+1} inputs: {r.inputs}", flush=True)
            
        print(f"\n--- NER Tool Calls ({len(ner_calls)}) ---", flush=True)
        for i, r in enumerate(ner_calls):
            print(f"Call {i+1} inputs: {r.inputs}", flush=True)
            # Check output size
            if r.outputs:
                out = str(r.outputs)
                print(f"  Output Size: {len(out)} chars", flush=True)
                if "results_file" in out:
                    print(f"  Refers to file: {out}", flush=True)
            else:
                print("  No output", flush=True)

    except Exception as e:
        print(f"Error during analysis: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze()
