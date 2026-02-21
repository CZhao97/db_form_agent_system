
import json
import glob
import re
import os

def trace_paper_funnel(ner_file_path, log_file_path):
    print(f"--- Tracing Funnel for {os.path.basename(ner_file_path)} ---")
    
    # 1. Load NER Cache
    with open(ner_file_path, 'r') as f:
        data = json.load(f)
        
    # Handle structure: { "MESH:ID": { "mentions": [...] } }
    # Or merged_output structure
    if "merged_output" in data:
        data = data["merged_output"]
    elif "per_file_results" in data: 
        # Should not happen for a single cache file but good to be safe
        pass
        
    raw_mentions_count = 0
    unique_entities = []
    
    for key, val in data.items():
        if isinstance(val, dict):
            mentions = val.get("mentions", [])
            raw_mentions_count += len(mentions)
            
            # Get the canonical name (usually the first mention or derived)
            # In this cache structure, we don't always have a "name" field explicitly 
            # but we can infer from mentions or key. 
            # Let's use the first mention text as a proxy for the name to search in logs
            if mentions:
                # Mention format often: "Text (Context: ...)"
                # We need to extract the "Text"
                first_mention = mentions[0]
                # Regex to grab text before parenthesis (approximate)
                match = re.match(r"^(.*?)\s*\(Context:", first_mention)
                name = match.group(1) if match else first_mention.split("(")[0].strip()
                unique_entities.append(name)
    
    unique_count = len(unique_entities)
    print(f"1. Raw Mentions: {raw_mentions_count}")
    print(f"2. Normalized (Unique Entities): {unique_count}")
    print(f"   Entities: {unique_entities[:10]}...") 

    # 3. Check Logs for Downstream Generation
    # We search for "decide whether '{name}'" or "Queries: ... {name}" 
    # The log format for query generation:
    # "Queries Online: ['... {name} ...']" 
    # OR the prompt sent to downstream: "According to the following definition..."
    
    # We will look for the query string construction in the logs
    # "According to the following definition, decide whether 'X'"
    
    verified_count = 0
    verified_entities = []
    
    if not os.path.exists(log_file_path):
        print("Log file not found.")
        return

    with open(log_file_path, 'r') as f:
        log_content = f.read()
        
    for entity in unique_entities:
        # Search for the entity in the "decide whether 'ENTITY'" pattern
        # Simple string matching might be enough
        pattern = f"decide whether '{entity}'"
        pattern2 = f"decide whether '{entity.lower()}'" 
        
        if pattern in log_content or pattern2 in log_content:
            verified_count += 1
            verified_entities.append(entity)
            
    print(f"3. Filtered (Agent Generated Queries): {verified_count}")
    print(f"   Verified: {verified_entities}")
    
    if unique_count > 0:
        print(f"   Reduction (Norm -> Filtered): {(1 - verified_count/unique_count)*100:.2f}%")

if __name__ == "__main__":
    ner_path = "agent/searching_results/case_study/dbp_eval_eval_0e17038a/10.1016j.watres.2023.120020.ner_cache.json"
    log_path = "ablation_full_restore_12.log"
    trace_paper_funnel(ner_path, log_path)
