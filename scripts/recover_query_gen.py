
import sys
import os
import json
from pathlib import Path
import time
from collections import defaultdict

# Add paths to make imports work
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir / "notebooks"))
sys.path.append(str(root_dir / "code"))

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from e2e_agent import query_generation_node, FullWorkflowState, REFINEMENT_PROMPT

def recover_ner_and_queries(session_dir_str):
    session_dir = Path(session_dir_str)
    lit_dir = session_dir / "literature_searching"
    
    print(f"📂 Scanning: {lit_dir}")
    
    merged_output = defaultdict(lambda: {"synonyms": [], "mentions": []})
    
    file_count = 0
    ner_found_count = 0
    
    # 1. Aggregate NER Results
    for json_file in lit_dir.glob("*.json"):
        if json_file.name == "chemical_ner_results.json" or json_file.name.endswith(".ner_cache.json"):
            continue
            
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if "cached_ner_results" in data:
                ner_str = data["cached_ner_results"]
                if isinstance(ner_str, str):
                    try:
                        ner_data = json.loads(ner_str)
                        if ner_data:
                            ner_found_count += 1
                            # Merge logic
                            for kb_id, details in ner_data.items():
                                # Merge synonyms
                                existing_syns = set(merged_output[kb_id]["synonyms"])
                                new_syns = details.get("synonyms", [])
                                for s in new_syns:
                                    if s: existing_syns.add(s)
                                merged_output[kb_id]["synonyms"] = list(existing_syns)
                                
                                # Merge mentions
                                mentions = details.get("mentions", [])
                                merged_output[kb_id]["mentions"].extend(mentions)
                    except json.JSONDecodeError:
                        pass
                        
            file_count += 1
            if file_count % 500 == 0:
                print(f"  Processed {file_count} files...")
                
        except Exception as e:
            print(f"Error reading {json_file.name}: {e}")

    print(f"✅ Processed {file_count} files.")
    print(f"✅ Found NER data in {ner_found_count} files.")
    print(f"✅ Aggregated {len(merged_output)} unique entities.")
    
    # Save the aggregated file
    # We need to restructure mentions to match ner_results_to_dataframe expectation:
    # { "mentions": [{"text": ["m1", "m2"]}] }
    
    final_merged = {}
    total_mentions = 0
    
    for kb_id, data in merged_output.items():
        unique_mentions = sorted(list(set(data["mentions"])))
        total_mentions += len(unique_mentions)
        final_merged[kb_id] = {
            "synonyms": data["synonyms"],
            "mentions": [{"text": unique_mentions}]
        }

    final_output = {
        "merged_output": final_merged,
        "mention_count": total_mentions
    }
    
    output_path = lit_dir / "chemical_ner_results.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=2)
    print(f"📄 Saved aggregated NER results to: {output_path}")
    
    # 2. Run Query Generation
    print("\n🚀 Running Query Generation Node...")
    
    # Mock state
    original_query = "Form a database of all experimentally confirmed disinfection byproducts (DBPs)"
    
    refined_definition = "An \"experimentally confirmed disinfection byproduct (DBP)\" is a chemical compound..."
    
    # IMPORTANT: Mock the upstream output so extract_final_output finds the file
    mock_upstream_output = json.dumps({"results_file": str(output_path)})
    
    mock_state = {
        "messages": [
            HumanMessage(content=f"{original_query}\n\nRefined Definition:\n{refined_definition}"),
            AIMessage(content=mock_upstream_output)
        ],
        "original_query": original_query,
        "search_session_dir": str(lit_dir),
        "iteration_count": 0,
        "refined_definition": refined_definition,
        "downstream_states": [],
        "refinement_messages": [],
        "is_satisfied": True,
        "final_reports": []
    }
    
    try:
        final_state = query_generation_node(mock_state)
        
        ds_states = final_state.get('downstream_states', [])
        print(f"\n\n✅ Query Generation Complete. Generated {len(ds_states)} downstream tasks.")
        
        if ds_states:
            print("\n--- Generated Queries ---")
            for i, ds in enumerate(ds_states):
                print(f"{i+1}. {ds['original_query']}")
                
            # Save generated queries
            q_out = session_dir / "recovered_queries.json"
            queries = [ds['original_query'] for ds in ds_states]
            with open(q_out, "w") as f:
                json.dump(queries, f, indent=2)
            print(f"\n📄 Saved queries to: {q_out}")
            
    except Exception as e:
        print(f"\n❌ Query Generation Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Point to the specific session directory
    target_session = root_dir / "agent" / "searching_results" / "e2e_run_20260125_130247"
    recover_ner_and_queries(target_session)
