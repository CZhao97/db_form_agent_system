import json
import re
from pathlib import Path

BASE_DIR = Path("/home/chen/GNPS_SIM/agent/db_form_agent_system")
NER_RESULTS_FILE = BASE_DIR / "agent/searching_results/e2e_run_20260125_130247/literature_searching/chemical_ner_results.json"
OUTPUT_FILE = BASE_DIR / "agent/searching_results/e2e_run_20260125_130247/recovered_queries_test_200.jsonl"

def get_inputs():
    with open(NER_RESULTS_FILE, 'r') as f:
        ner_data = json.load(f)
        
    merged_output = ner_data.get("merged_output", {})
    if not merged_output and ner_data.get("per_file_results"):
         # Aggregate logic matching batch_query_gen.py
         aggregated = {}
         for file_entry in ner_data["per_file_results"]:
             entities = file_entry.get("entities", {})
             for kb_id, details in entities.items():
                 if kb_id not in aggregated:
                     aggregated[kb_id] = {"mentions": [], "synonyms": details.get("synonyms", [])}
                 aggregated[kb_id]["mentions"].extend(details.get("mentions", []))
         
         final_aggregated = {}
         for kb_id, data in aggregated.items():
             unique = sorted(list(set(data["mentions"])))
             final_aggregated[kb_id] = {"synonyms": data["synonyms"], "mentions": [{"text": unique}]}
         merged_output = final_aggregated

    all_input_clusters = []
    for kb_id, data in merged_output.items():
        mentions = []
        for m_grp in data.get("mentions", []):
            if isinstance(m_grp, dict):
                mentions.extend(m_grp.get("text", []))
            elif isinstance(m_grp, list):
                mentions.extend(m_grp)
        unique = list(set([m for m in mentions if m and isinstance(m, str)]))
        if len(unique) > 10: unique = unique[:10]
        if unique:
            all_input_clusters.append(unique[0]) # Just take the first name as representative for display
            
    return all_input_clusters[:200]

def get_outputs():
    names = []
    if not OUTPUT_FILE.exists():
        return []
        
    with open(OUTPUT_FILE, 'r') as f:
        for line in f:
            data = json.loads(line)
            query = data.get("query", "")
            # Extract name from query: "...decide whether 'NAME' is..."
            match = re.search(r"decide whether '(.*?)' is", query)
            if match:
                names.append(match.group(1))
    return names

def main():
    inputs = get_inputs()
    outputs = get_outputs()
    
    print(f"--- Original Inputs (First {len(inputs)}) ---")
    for i, name in enumerate(inputs):
        print(f"{i+1}. {name}")
        
    print("\n" + "="*50 + "\n")
    
    print(f"--- Remained (Filtered) ({len(outputs)}) ---")
    for i, name in enumerate(outputs):
        print(f"{i+1}. {name}")

    print("\n" + "="*50 + "\n")
    print(f"Retention Rate: {len(outputs)}/{len(inputs)} ({len(outputs)/len(inputs)*100:.1f}%)")

if __name__ == "__main__":
    main()
