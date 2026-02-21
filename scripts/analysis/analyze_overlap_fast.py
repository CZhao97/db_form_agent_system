
import json
import pandas as pd
import sys
import os
import time

# Paths
EXCEL_PATH = '/home/chen/GNPS_SIM/agent/db_form_agent_system/es4c13900_si_001.xlsx'
JSON_PATH = '/home/chen/GNPS_SIM/agent/searching_results/run_20260218_193647/ner_results/chemical_ner_results.json'

def main():
    print(f"[DEBUG] Script started", flush=True)
    
    # 2. Load NER Results (Fastest)
    print(f"[DEBUG] Loading JSON...", flush=True)
    try:
        with open(JSON_PATH, 'r') as f:
            data = json.load(f)
        print(f"[DEBUG] JSON Loaded. Keys: {list(data.keys())}", flush=True)
    except Exception as e:
        print(f"[ERROR] JSON Error: {e}", flush=True)
        return

    # Extract names
    found_chemicals = set()
    if 'per_file_results' in data:
        for file_res in data['per_file_results']:
            entities = file_res.get('entities', {})
            for entity_id, info in entities.items():
                mentions = info.get('mentions', [])
                for m in mentions:
                    if "(Context:" in m: m = m.split("(Context:")[0]
                    found_chemicals.add(m.strip().lower())
    
    print(f"[DEBUG] Found {len(found_chemicals)} unique chemicals.", flush=True)

    # 1. Load Excel DBPs
    print(f"[DEBUG] Loading Excel {EXCEL_PATH}...", flush=True)
    try:
        # Explicit engine
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=1, engine='openpyxl')
        print(f"[DEBUG] Excel Loaded. Columns: {df.columns.tolist()}", flush=True)
    except Exception as e:
        print(f"[ERROR] Excel Error: {e}", flush=True)
        return

    if 'IUPAC name' not in df.columns:
        print("[WARN] Header mismatch, trying header=0", flush=True)
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=0, engine='openpyxl')
    
    if 'IUPAC name' not in df.columns:
         print(f"[ERROR] 'IUPAC name' missing. Cols: {df.columns.tolist()}", flush=True)
         return

    dbp_set = set(df['IUPAC name'].dropna().astype(str).str.strip().str.lower().tolist())
    print(f"[DEBUG] Reference DBPs: {len(dbp_set)}", flush=True)
    
    # 3. Overlap
    intersection = dbp_set.intersection(found_chemicals)
    
    print("-" * 30, flush=True)
    print(f"Confirmed DBPs found: {len(intersection)}", flush=True)
    print(f"Percentage covered: {len(intersection) / len(dbp_set) * 100:.2f}%", flush=True)
    print("-" * 30, flush=True)
    
    for x in list(intersection)[:5]:
        print(f" - {x}", flush=True)

if __name__ == "__main__":
    main()
