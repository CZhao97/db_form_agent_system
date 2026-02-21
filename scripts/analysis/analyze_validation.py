
import json
import os
import statistics
import numpy as np

def analyze_results():
    if not os.path.exists("validation_results.jsonl"):
        print("validation_results.jsonl not found.")
        return

    results = []
    with open("validation_results.jsonl", "r") as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
        
    num_papers = len(results)
    total_inputs = sum(r["input_count"] for r in results)
    
    # Use accepted_ids for the count if available, else fallback
    # The new script guarantees 'accepted_count' and 'accepted_ids'
    total_accepted = sum(r.get("accepted_count", 0) for r in results)
    
    global_reduction_rate = (1 - (total_accepted / total_inputs)) * 100 if total_inputs > 0 else 0
    
    print("-" * 60)
    print(f"Validation Run Analysis (N={num_papers})")
    print("-" * 60)
    print(f"Total Input Entities:      {total_inputs}")
    print(f"Total Accepted Entities:   {total_accepted}")
    print(f"Global Reduction Rate:     {global_reduction_rate:.2f}%")
    print("-" * 60)
    
    # Per-Paper Stats
    acceptance_rates = []
    for r in results:
        inp = r["input_count"]
        acc = r.get("accepted_count", 0)
        rate = (acc / inp) * 100 if inp > 0 else 0
        acceptance_rates.append(rate)
        
    mean_acc = statistics.mean(acceptance_rates)
    median_acc = statistics.median(acceptance_rates)
    stdev_acc = statistics.stdev(acceptance_rates) if len(results) > 1 else 0
    
    print(f"Per-Paper Acceptance Rate (%):")
    print(f"  Mean:   {mean_acc:.2f}%")
    print(f"  Median: {median_acc:.2f}%")
    print(f"  SD:     {stdev_acc:.2f}%")
    print(f"  Range:  {min(acceptance_rates):.1f}% - {max(acceptance_rates):.1f}%")
    print("-" * 60)
    
    # Qualitative: Sample accepted vs rejected
    print("\nSample Output (Paper 1):")
    if results:
        r = results[0]
        print(f"Paper: {r.get('paper', 'Unknown')}")
        print(f"Input: {r['input_count']} -> Accepted: {r['accepted_count']}")
        print(f"First 5 Accepted IDs: {r.get('accepted_ids', [])[:5]}")
        print(f"First 3 Queries: {json.dumps(r.get('queries', [])[:3], indent=2)}")

if __name__ == "__main__":
    analyze_results()
