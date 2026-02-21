
import os
import sys

# MOCK SQLITE to bypass broken env (MUST BE BEFORE IMPORTS)
from unittest.mock import MagicMock
sys.modules["sqlite3"] = MagicMock()
sys.modules["sqlite3.dbapi2"] = MagicMock()

import pandas as pd
from langsmith import Client
from datetime import datetime
from dotenv import load_dotenv

# Setup
load_dotenv()
client = Client()

RUN_ID = "d24c9334-5b8c-4c98-b032-b53f6f164314"

def analyze_run(run_id):
    print(f"Debug: Checking API Key...")
    if not os.environ.get("LANGCHAIN_API_KEY"):
        print("Error: LANGCHAIN_API_KEY not found in environment.")
        return

    print(f"Fetching Run: {run_id}")
    try:
        # Fetch the root run
        run = client.read_run(run_id)
        print(f"Run Name: {run.name}")
        print(f"Status: {run.status}")
        print(f"Inputs: {run.inputs.keys()}")
        print(f"Output: {str(run.outputs)[:500]}...")
        
        # List child runs (Tools, LLM calls)
        child_runs = list(client.list_runs(run_type="tool", execution_order=1)) 
        # Actually filter by parent_run_id is better if possible, but list_runs filters are specific.
        # Let's use the trace_id from the root run.
        trace_id = run.trace_id
        print(f"Trace ID: {trace_id}")
        
        all_trace_runs = list(client.list_runs(trace_id=trace_id))
        print(f"Total Trace Items: {len(all_trace_runs)}")
        
        # Analyze Search Tool Calls
        search_runs = [r for r in all_trace_runs if r.name == "fulltext_journal_search"]
        print(f"\n--- Search Tool Calls ({len(search_runs)}) ---")
        for i, r in enumerate(search_runs):
            print(f"Call {i+1}:")
            print(f"  Inputs: {r.inputs}")
            # Output might be large, truncate
            out = str(r.outputs)
            print(f"  Result Length: {len(out)}")
            if "total_results" in out:
                print(f"  (Likely contains results)")

        # Analyze NER Tool Calls
        ner_runs = [r for r in all_trace_runs if r.name == "chemical_ner"]
        print(f"\n--- NER Tool Calls ({len(ner_runs)}) ---")
        for i, r in enumerate(ner_runs):
            print(f"Call {i+1}:")
            print(f"  Inputs: {r.inputs}")
            print(f"  Outputs: {str(r.outputs)[:500]}...")

        # Analyze Inspect Tool Calls
        inspect_runs = [r for r in all_trace_runs if r.name == "inspect_search_results"]
        print(f"\n--- Inspect Tool Calls ({len(inspect_runs)}) ---")
        for i, r in enumerate(inspect_runs):
            print(f"Call {i+1}:")
            print(f"  Inputs: {r.inputs}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_run(RUN_ID)
