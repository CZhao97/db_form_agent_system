
import json
import pandas as pd
import sys
import os

# Paths
EXCEL_PATH = '/home/chen/GNPS_SIM/agent/db_form_agent_system/es4c13900_si_001.xlsx'
JSON_PATH = '/home/chen/GNPS_SIM/agent/searching_results/run_20260218_193647/ner_results/chemical_ner_results.json'

def main():
    # 1. Load Excel DBPs
    print(f"Loading {EXCEL_PATH}...")
    try:
        # Based on previous knowledge, header is likely row 1 (index 1)
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=1)
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    # Check columns
    if 'IUPAC name' not in df.columns:
        # Fallback logic if header detection failed
        print("Standard header not found, trying header=0...")
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=0)
    
    if 'IUPAC name' not in df.columns:
         print(f"Could not find 'IUPAC name' column. Available: {df.columns.tolist()}")
         return

    dbp_list = df['IUPAC name'].dropna().astype(str).tolist()
    # Normalize: lower, strip
    dbp_set = set(n.strip().lower() for n in dbp_list)
    
    print(f"Total reference DBPs in Excel: {len(dbp_set)}")
    
    # 2. Load NER Results
    print(f"Loading {JSON_PATH}...")
    try:
        with open(JSON_PATH, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON: {e}")
        return

    # Extract names from mentions
    found_chemicals = set()
    
    # Check if 'per_file_results' exists (it should in the new format)
    if 'per_file_results' in data:
        for file_res in data['per_file_results']:
            entities = file_res.get('entities', {})
            for entity_id, info in entities.items():
                # Get canonical name/synonyms if available (better recall?)
                # For now, let's stick to mentions as "what was found in text"
                mentions = info.get('mentions', [])
                for m in mentions:
                    if "(Context:" in m:
                        name = m.split("(Context:")[0].strip()
                    else:
                        name = m.strip()
                    if name:
                        found_chemicals.add(name.lower())
    
    print(f"Total unique chemicals found in NER: {len(found_chemicals)}")
    
    # 3. Calculate Overlap
    intersection = dbp_set.intersection(found_chemicals)
    
    print("-" * 30)
    print(f"Confirmed DBPs found in NER results: {len(intersection)}")
    print(f"Percentage covered: {len(intersection) / len(dbp_set) * 100:.2f}%")
    print("-" * 30)
    
    # List some examples
    print("Example matches:")
    for x in list(intersection)[:10]:
        print(f" - {x}")

if __name__ == "__main__":
    main()
