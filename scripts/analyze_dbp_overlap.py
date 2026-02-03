import json
import pandas as pd
import sys
import os

# Paths
EXCEL_PATH = 'es4c13900_si_001.xlsx'
JSON_PATH = 'agent/searching_results/e2e_run_20260125_130247/literature_searching/ner_results/chemical_ner_results.json'

def main():
    # 1. Load Excel DBPs
    print(f"Loading {EXCEL_PATH}...")
    try:
        # Based on previous inspection, the header is likely at row index 1 (0-based) because row 0 was the description
        # Wait, previous output showed df.columns was the long text, and row 0 was "IUPAC name".
        # So we should use header=1.
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=1)
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    # Check columns
    if 'IUPAC name' not in df.columns:
        print(f"Warning: 'IUPAC name' not found in columns: {df.columns.tolist()}")
        # Check if it's in the first row instead
        # Sometimes header=1 is wrong if pandas read it differently.
        # Let's try to find the column dynamically or just fallback
        possible_col = [c for c in df.columns if "IUPAC" in str(c)]
        if not possible_col:
             # Try reloading with header=0 and check row 0
             df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=0)
             if 'IUPAC name' in df.iloc[0].values:
                 df.columns = df.iloc[0]
                 df = df[1:]
    
    if 'IUPAC name' not in df.columns:
         print("Could not find 'IUPAC name' column. Exiting.")
         print("Columns found:", df.columns)
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
    
    if 'per_file_results' in data:
        for file_res in data['per_file_results']:
            entities = file_res.get('entities', {})
            for entity_id, info in entities.items():
                mentions = info.get('mentions', [])
                for m in mentions:
                    # Clean mention: "Name (Context: ...)" -> "Name"
                    if "(Context:" in m:
                        name = m.split("(Context:")[0].strip()
                    else:
                        name = m.strip()
                    
                    if name:
                        found_chemicals.add(name.lower())
    
    print(f"Total unique chemicals found in NER: {len(found_chemicals)}")
    
    # 3. Calculate Overlap
    # Filter: Which DBPs from Excel are in NER results?
    intersection = dbp_set.intersection(found_chemicals)
    
    print("-" * 30)
    print(f"Confirmed DBPs found in NER results: {len(intersection)}")
    print(f"Percentage covered: {len(intersection) / len(dbp_set) * 100:.2f}%")
    print("-" * 30)
    
    # Optional: Check exact matches vs partial or synonym needs
    # (For now, strict string match on lowercased name)

if __name__ == "__main__":
    main()
