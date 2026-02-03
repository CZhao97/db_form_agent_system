
import sys
import os
import json

# Set environment before importing modules
for key, val in {'INCLUDE_OFFLINE_SEARCH': 'False', 'INCLUDE_ONLINE_SEARCH': 'True', 'LANGCHAIN_PROJECT': 'DBP_Stability_Test_Run_2', 'LANGCHAIN_DEBUG': 'true', 'NODE_LOGS': '1'}.items():
    os.environ[key] = val

# Add paths to handle sibling imports correctly
sys.path.insert(0, os.path.join(os.getcwd(), "notebooks"))
sys.path.insert(0, os.getcwd())

from evaluate_dbp_downstream_only import evaluate_compound

from langchain_community.callbacks import get_openai_callback
 
compounds = ['2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione']
 
print(f"\n============================================================")
print(f"MODE: ONLINE ONLY RUN 2")
print(f"============================================================\n")
 
results = []
for compound in compounds:
    print(f"\n>>> Processing: {compound} <<<")
    try:
        with get_openai_callback() as cb:
            result = evaluate_compound(compound)
        result["tokens_used"] = cb.total_tokens
        result["cost_usd"] = round(cb.total_cost, 6)
        results.append(result)
        print(f"Result: {result['normalized_prediction']} (Raw: {str(result['agent_verdict'])[:50]}...) (Tokens: {result['tokens_used']})")
    except Exception as e:
        print(f"ERROR processing {compound}: {e}")
        results.append({'input_compound': compound, 'agent_verdict': 'Error'})

# Print summary
print(f"\n============================================================")
print(f"SUMMARY: ONLINE ONLY RUN 2")
print(f"============================================================")
for r in results:
    print(f"{r['input_compound']:30s} -> {r['agent_verdict']}")
