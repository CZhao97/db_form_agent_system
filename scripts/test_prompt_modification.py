#!/usr/bin/env python3
"""
Test the modified prompt to verify it generates unquoted queries.
This script runs a single DBP evaluation and checks the generated queries.
"""
import sys
import os
import json

# Add paths
sys.path.insert(0, os.path.join(os.getcwd(), "notebooks"))
sys.path.insert(0, os.getcwd())

from evaluate_dbp_downstream_only import evaluate_compound

print("="*70)
print("TESTING MODIFIED PROMPT: Unquoted Query Generation")
print("="*70)

# Test compound
compound = "4-Bromophenol"

print(f"\nEvaluating: {compound}")
print("Expected behavior:")
print("  - Queries should NOT contain quoted terms like '\"4-Bromophenol\"'")
print("  - Queries should use simple terms like '4-Bromophenol disinfection'")
print("  - Should find papers from offline DB")
print(f"\n{'='*70}\n")

result = evaluate_compound(compound)

print(f"\n{'='*70}")
print("RESULT SUMMARY:")
print(f"{'='*70}")
print(f"Compound: {result['input_compound']}")
print(f"Verdict: {result['agent_verdict']}")
print(f"Normalized: {result['normalized_prediction']}")
print(f"Session Dir: {result['session_dir']}")

# Check session files for query format
session_dir = result['session_dir']
if session_dir and os.path.exists(session_dir):
    print(f"\n{'='*70}")
    print("CHECKING GENERATED QUERIES:")
    print(f"{'='*70}")
    
    # Look for search result files
    import glob
    search_dirs = glob.glob(os.path.join(session_dir, "run_*"))
    
    if search_dirs:
        for search_dir in search_dirs[:3]:  # Check first 3 runs
            index_file = os.path.join(search_dir, "index.ndjson")
            if os.path.exists(index_file):
                print(f"\nSearch run: {os.path.basename(search_dir)}")
                # Check if we got results
                with open(index_file, 'r') as f:
                    papers = [json.loads(line) for line in f]
                print(f"  Papers found: {len(papers)}")
                if papers:
                    sources = {}
                    for p in papers:
                        source = p.get('source', 'Unknown')
                        sources[source] = sources.get(source, 0) + 1
                    print(f"  Sources: {sources}")
    else:
        print("  No search runs found")

print(f"\n{'='*70}")
print("TEST COMPLETE")
print(f"{'='*70}")
print("\nTo verify query format manually, check:")
print(f"  {session_dir}")
print("Look for unquoted queries in agent logs")
