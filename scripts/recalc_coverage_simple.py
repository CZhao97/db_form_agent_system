
import sys
# MOCK SQLITE (CRITICAL: Must be first)
from unittest.mock import MagicMock
sys.modules["sqlite3"] = MagicMock()
sys.modules["sqlite3.dbapi2"] = MagicMock()

import json
import pandas as pd
import os
import sys
import glob

# Constants
EXCEL_PATH = 'es4c13900_si_001.xlsx'
SEARCH_RESULTS_DIR = '/home/chen/GNPS_SIM/agent/searching_results'

def load_data():
    print(f"Loading Reference from {EXCEL_PATH}...")
    try:
        df = pd.read_excel(EXCEL_PATH)
        if "Name" in df.columns:
            ref_dbps = set(df["Name"].dropna().astype(str).str.lower().str.strip())
        else:
            # Fallback to 2nd column
            ref_dbps = set(df.iloc[:, 1].dropna().astype(str).str.lower().str.strip())
        print(f"Loaded {len(ref_dbps)} reference DBPs.")
    except Exception as e:
        print(f"Error loading Excel: {e}")
        return set(), set()

    found_entities = set()
    
    # Glob for all JSON results
    json_files = glob.glob(os.path.join(SEARCH_RESULTS_DIR, "run_*", "ner_results", "chemical_ner_results.json"))
    # Also check without "ner_results" subdir just in case structure varies
    # But usually it is run_.../ner_results/chemical_ner_results.json
    
    if not json_files:
        print("No NER results found in searching_results/run_*/ner_results/...")
        # Try checking for any chemical_ner_results.json recursively
        json_files = glob.glob(os.path.join(SEARCH_RESULTS_DIR, "**", "chemical_ner_results.json"), recursive=True)

    print(f"Found {len(json_files)} NER result files.")
    
    for json_path in json_files:
        print(f"Loading NER Results from {json_path}...")
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
                
            # Parse 'per_file_results' which contains entities
            if "per_file_results" in data:
                for filename, results in data["per_file_results"].items():
                     if "entities" in results:
                         for entity in results["entities"]:
                             text = None
                             if isinstance(entity, dict) and "text" in entity:
                                 text = entity["text"]
                             elif isinstance(entity, str):
                                 text = entity
                             
                             if text:
                                 found_entities.add(text.lower().strip())
            
            # Also check 'chemical_mentions' if available (sometimes different format)
            if "chemical_mentions" in data:
                 for m in data["chemical_mentions"]:
                     text = None
                     if isinstance(m, dict) and "text" in m:
                         text = m["text"]
                     elif isinstance(m, str):
                         text = m
                     
                     if text:
                         found_entities.add(text.lower().strip())

        except Exception as e:
            print(f"Error loading JSON {json_path}: {e}")

    print(f"Parsed all files. Found {len(found_entities)} unique entities.")
    return ref_dbps, found_entities

def calculate_coverage():
    ref_dbps, found_entities = load_data()
    
    if not ref_dbps:
        print("No reference DBPs loaded.")
        return

    # Calculate Intersection
    # Exact Match Logic
    intersection = ref_dbps.intersection(found_entities)
    
    print("\n--- RESULTS ---")
    print(f"Total Reference DBPs: {len(ref_dbps)}")
    print(f"Found in Upstream Test: {len(intersection)}")
    coverage = (len(intersection) / len(ref_dbps)) * 100
    print(f"Coverage Ratio: {coverage:.2f}%")
    
    print("\nExamples Found:")
    for x in list(intersection)[:10]:
        print(f" - {x}")

if __name__ == "__main__":
    calculate_coverage()
