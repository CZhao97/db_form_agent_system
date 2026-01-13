
import json
import pandas as pd
from pathlib import Path

def load_ner_results(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def ner_results_to_dataframe(ner_data, include_synonyms=False):
    merged = ner_data.get("merged_output", {})
    if not merged:
        return pd.DataFrame()
    
    rows = []
    for kb_id, details in merged.items():
        mentions_data = details.get("mentions", [])
        
        # Flatten mentions
        all_mentions = []
        if isinstance(mentions_data, list):
            for m in mentions_data:
                if isinstance(m, dict) and "text" in m:
                    # It might be list or string
                    txt = m["text"]
                    if isinstance(txt, list):
                        all_mentions.extend(txt)
                    else:
                        all_mentions.append(txt)
                elif isinstance(m, str):
                    all_mentions.append(m)
        
        unique_mentions = sorted(list(set(all_mentions)))
        
        row = {
            "kb_id": kb_id,
            "unique_mentions": unique_mentions,
            "mention_count": len(all_mentions), 
            "synonyms": details.get("synonyms", [])
        }
        rows.append(row)
        
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("mention_count", ascending=False)
        
    return df
