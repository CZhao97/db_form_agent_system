"""
Helper module for loading and displaying Chemical NER results from saved files.
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, List


def load_ner_results(file_path: str) -> Dict[str, Any]:
    """
    Load Chemical NER results from a JSON file.
    
    Args:
        file_path: Path to the saved NER results JSON file
    
    Returns:
        Dictionary containing the NER results
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def ner_results_to_dataframe(ner_data: Dict[str, Any], include_synonyms: bool = True) -> pd.DataFrame:
    """
    Convert NER results to a pandas DataFrame for easier viewing and analysis.
    
    Args:
        ner_data: The loaded NER results dictionary
        include_synonyms: Whether to include synonym columns
    
    Returns:
        pandas DataFrame with flattened NER results
    """
    if "error" in ner_data and ner_data["error"]:
        raise ValueError(f"NER results contain error: {ner_data.get('message', 'Unknown error')}")
    
    merged_data = ner_data.get("merged_output", {})
    
    rows = []
    for kb_id, value in merged_data.items():
        synonyms = value.get("synonyms", [])
        mentions_list = value.get("mentions", [])
        
        # Extract mention texts
        mention_texts = []
        if mentions_list:
            for mention_entry in mentions_list:
                if isinstance(mention_entry, dict):
                    text_list = mention_entry.get("text", [])
                    if isinstance(text_list, list):
                        mention_texts.extend(text_list)
                    elif isinstance(text_list, str):
                        mention_texts.append(text_list)
        
        row = {
            "kb_id": kb_id if kb_id else "UNLINKED",
            "mention_count": len(mention_texts),
            "unique_mentions": ", ".join(sorted(set(mention_texts))) if mention_texts else "",
        }
        
        if include_synonyms:
            row["synonym_count"] = len(synonyms)
            row["top_synonyms"] = ", ".join(synonyms[:5]) if synonyms else ""
            row["all_synonyms"] = ", ".join(synonyms) if synonyms else ""
        
        rows.append(row)
    
    df = pd.DataFrame(rows)
    
    # Sort by mention count descending
    if not df.empty and "mention_count" in df.columns:
        df = df.sort_values("mention_count", ascending=False).reset_index(drop=True)
    
    return df


def print_ner_summary(file_path: str, top_n: int = 20, include_synonyms: bool = True):
    """
    Print a summary of NER results from a file.
    
    Args:
        file_path: Path to the saved NER results JSON file
        top_n: Number of top entities to display
        include_synonyms: Whether to show synonyms
    """
    print(f"\n{'='*60}")
    print(f"Chemical NER Results: {file_path}")
    print(f"{'='*60}\n")
    
    data = load_ner_results(file_path)
    
    if "error" in data and data["error"]:
        print(f"❌ Error: {data.get('message', 'Unknown error')}")
        return
    
    mention_count = data.get("mention_count", 0)
    merged_count = len(data.get("merged_output", {}))
    
    print(f"Total mentions: {mention_count}")
    print(f"Unique entities (KB IDs): {merged_count}\n")
    
    df = ner_results_to_dataframe(data, include_synonyms=include_synonyms)
    
    if df.empty:
        print("No entities extracted.")
        return
    
    # Display top entities
    display_cols = ["kb_id", "mention_count", "unique_mentions"]
    if include_synonyms:
        display_cols.append("top_synonyms")
    
    print(f"Top {min(top_n, len(df))} entities:\n")
    pd.set_option('display.max_colwidth', 100)
    print(df[display_cols].head(top_n).to_string(index=True))
    print("\n")


def extract_ner_file_path(agent_output: str) -> Optional[str]:
    """
    Extract the NER results file path from agent output.
    
    Args:
        agent_output: The agent's output string (potentially JSON)
    
    Returns:
        File path if found, None otherwise
    """
    try:
        # Try parsing as JSON
        data = json.loads(agent_output)
        if isinstance(data, dict):
            return data.get("results_file") or data.get("ner_results_file")
    except json.JSONDecodeError:
        pass
    
    # Try regex extraction
    import re
    match = re.search(r'"results_file"\s*:\s*"([^"]+)"', agent_output)
    if match:
        return match.group(1)
    
    match = re.search(r'chemical_ner_results_\d+\.json', agent_output)
    if match:
        return match.group(0)
    
    return None


def get_latest_ner_results(session_dir: str) -> Optional[str]:
    """
    Find the most recent NER results file in a session directory.
    
    Args:
        session_dir: Path to the session directory
    
    Returns:
        Path to the latest NER results file, or None if not found
    """
    session_path = Path(session_dir)
    
    if not session_path.exists():
        return None
    
    ner_files = sorted(session_path.glob("chemical_ner_results_*.json"))
    
    if not ner_files:
        return None
    
    return str(ner_files[-1])