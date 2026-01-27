import re
import json

def analyze_logs():
    log_path = "stability_test_online_only.log"
    try:
        with open(log_path, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print("Log file not found.")
        return

    # Split by Run/Processing separator
    runs = content.split(">>> Processing:")
    
    # Skip preamble (index 0)
    for i, run_text in enumerate(runs[1:], 1):
        print(f"\n{'='*40}")
        print(f"RUN {i}")
        print(f"{'='*40}")
        
        # Find split points
        parts = run_text.split("[Researcher Output]:")
        if len(parts) < 2:
             print("No Researcher Output found.")
             continue
             
        for idx, part in enumerate(parts[1:]):
            # The content is before "[Critique Output]" if present, or end of string
            # Also need to handle if multiple outputs are chained?
            # Actually, split gives us the text starting with the JSON. I need to find where it ends.
            
            # Clean up: Find first { and last }
            # Usually followed by [Critique Output]
            json_text = part.split("[Critique Output]:")[0]
            
            start_idx = json_text.find("{")
            end_idx = json_text.rfind("}")
            
            if start_idx == -1 or end_idx == -1:
                print(f"  Step {idx+1}: No JSON braces found.")
                continue
                
            clean_block = json_text[start_idx : end_idx+1]
            
            try:
                data = json.loads(clean_block)
                
                # Check verdict
                claim = "Unknown"
                if "verdict_statement" in data:
                    claim = data["verdict_statement"].get("claim", "Unknown")
                elif "synthesis" in data:
                    claim = data["synthesis"].get("claim", "Unknown")
                    
                # Check queries
                queries = []
                if "search_methodology" in data:
                    queries = data["search_methodology"].get("queries_executed", [])
                
                # Only print the LAST one if there are multiple steps?
                # Actually, let's print all steps to see the evolution.
                print(f"  Step {idx+1}: Claim = {claim}")
                print("  Queries Executed:")
                for q in queries:
                    print(f"    - {q}")
            except json.JSONDecodeError as e:
                print(f"  Step {idx+1}: (Invalid JSON block) - {e}")
                # print(clean_block[:200] + "...")

if __name__ == "__main__":
    analyze_logs()
