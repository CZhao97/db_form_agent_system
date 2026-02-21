
import json
import pandas as pd
import os
import time
import logging
import pubchempy as pcp
import matplotlib.pyplot as plt

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
EXCEL_PATH = 'es4c13900_si_001.xlsx'
JSON_PATH = '/home/chen/GNPS_SIM/agent/searching_results/run_20260218_193647/ner_results/chemical_ner_results.json'
OUTPUT_PLOT = 'dbp_coverage_plot_pubchem.png'
CACHE_FILE = 'pubchem_synonym_cache.json'
OUTPUT_CSV = 'pubchem_normalization_mapping.csv'

def load_data():
    # 1. Load Excel DBPs (Reference)
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=1)
        if 'IUPAC name' not in df.columns:
             df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=0)
             if 'IUPAC name' in df.iloc[0].values:
                 df.columns = df.iloc[0]
                 df = df[1:]
        reference_dbps = df['IUPAC name'].dropna().astype(str).unique().tolist()
    except Exception as e:
        logging.error(f"Error reading Excel: {e}")
        return [], []

    # 2. Load Found Chemicals (NER Results)
    try:
        with open(JSON_PATH, 'r') as f:
            data = json.load(f)
        
        found_names = set()
        if 'per_file_results' in data:
            for file_res in data['per_file_results']:
                entities = file_res.get('entities', {})
                for entity_id, info in entities.items():
                    for m in info.get('mentions', []):
                         name = m.split("(Context:")[0].strip() if "(Context:" in m else m.strip()
                         if name: found_names.add(name.lower())
                    for s in info.get('synonyms', []):
                        found_names.add(s.lower())
    except Exception as e:
        logging.error(f"Error reading JSON: {e}")
        return [], []
        
    return reference_dbps, found_names

def get_pubchem_synonyms(name, cache):
    if name in cache:
        return cache[name]
    
    try:
        logging.info(f"Querying PubChem for: {name}")
        compounds = pcp.get_compounds(name, 'name')
        if compounds:
            c = compounds[0]
            syns = c.synonyms
            # Add IUPAC name and common name
            if c.iupac_name: syns.append(c.iupac_name)
            
            # Normalize list
            syns = list(set([s.lower() for s in syns]))
            cache[name] = {'cid': c.cid, 'synonyms': syns}
            time.sleep(0.5) # Rate limit
            return cache[name]
    except Exception as e:
        logging.warning(f"PubChem Error for {name}: {e}")
    
    cache[name] = {'cid': None, 'synonyms': []} # Cache miss
    return cache[name]

def main():
    refs, found_names_set = load_data()
    if not refs: return

    # Load Cache
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
            
    matches = {}
    
    try:
        for i, ref in enumerate(refs):
            if i % 10 == 0: logging.info(f"Processing {i}/{len(refs)}...")
            
            # 1. Exact Check first (Fast)
            if ref.lower() in found_names_set:
                matches[ref] = {"match_type": "exact", "candidate": ref}
                continue
                
            # 2. PubChem Check
            data = get_pubchem_synonyms(ref, cache)
            synonyms = data.get('synonyms', [])
            
            match_found = False
            for s in synonyms:
                if s in found_names_set:
                    matches[ref] = {"match_type": "pubchem_synonym", "candidate": s, "cid": data.get('cid')}
                    match_found = True
                    break
            
            if not match_found:
                 # Check partial match? No, stick to strict synonym for now.
                 pass
                 
    except KeyboardInterrupt:
        logging.warning("Interrupted! Saving partial cache...")
    finally:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)

    # Stats
    total = len(refs)
    recovered = len(matches)
    logging.info(f"Total: {total}, Recovered: {recovered} ({recovered/total:.2%})")
    
    # Save CSV
    pd.DataFrame([{ "Reference": k, "Type": v["match_type"], "Candidate": v.get("candidate"), "CID": v.get("cid") } for k,v in matches.items()]).to_csv(OUTPUT_CSV, index=False)

    # Plot
    labels = [f'Recovered ({recovered})', f'Not Found ({total - recovered})']
    sizes = [recovered, total - recovered]
    colors = ['#66b3ff', '#ff9999']
    
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140)
    plt.title(f"Coverage of Reference DBPs (PubChem Synonym Resolution)\nTotal: {total}", fontsize=14)
    plt.savefig(OUTPUT_PLOT)
    logging.info(f"Plot saved to {OUTPUT_PLOT}")

if __name__ == "__main__":
    main()
