
import json
import pandas as pd
import logging

# Setup
logging.basicConfig(level=logging.INFO, format='%(message)s')

JSON_PATH = 'agent/searching_results/e2e_run_20260125_130247/literature_searching/ner_results/chemical_ner_results.json'
CSV_PATH = 'dbp_normalization_mapping.csv'

def main():
    # 1. Load Found MeSH IDs from NER JSON
    found_mesh_ids = set()
    try:
        with open(JSON_PATH, 'r') as f:
            data = json.load(f)
            # keys of top level dict are MeSH IDs? Let's check.
            # Usually structure is { "MESH:D0001": {...}, ... }
            found_mesh_ids.update(data.keys())
            
            # double check per-file
            if 'per_file_results' in data:
                for res in data['per_file_results']:
                    if 'entities' in res:
                        found_mesh_ids.update(res['entities'].keys())
    except Exception as e:
        logging.error(f"Error reading JSON: {e}")
        return

    logging.info(f"Found {len(found_mesh_ids)} unique MeSH IDs in literature.")

    # 2. Load Mapped MeSH IDs from CSV
    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        logging.error(f"Error reading CSV: {e}")
        return

    total_refs = len(df)
    
    # 3. Calculate Intersection
    recovered_count = 0
    
    for _, row in df.iterrows():
        mid = str(row.get('mesh_id', '')).strip()
        if mid and mid in found_mesh_ids:
            recovered_count += 1
            
    logging.info(f"Total References: {total_refs}")
    logging.info(f"Recovered via MeSH: {recovered_count}")
    logging.info(f"Coverage: {recovered_count/total_refs:.2%}")

if __name__ == "__main__":
    main()
