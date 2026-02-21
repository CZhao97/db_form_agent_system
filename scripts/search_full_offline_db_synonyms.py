
import os
import sys
import lancedb
import json
import pandas as pd
import logging
from tqdm import tqdm

# Configuration
LANCEDB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"
EXCEL_PATH = "es4c13900_si_001.xlsx"
INTEGRATED_CSV = "integrated_normalization_mapping.csv"
PUBCHEM_CACHE = "pubchem_synonym_cache.json"
OUTPUT_CSV = "offline_db_coverage_synonyms.csv"

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')

def load_missing_dbps():
    # Load All
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=1)
        if 'IUPAC name' not in df.columns:
             df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=0)
             if 'IUPAC name' in df.iloc[0].values:
                 df.columns = df.iloc[0]
                 df = df[1:]
        all_refs = set(df['IUPAC name'].dropna().astype(str).unique())
    except Exception as e:
        logging.error(f"Error reading Excel: {e}")
        return []

    # Load Recovered
    try:
        df_integrated = pd.read_csv(INTEGRATED_CSV)
        recovered_refs = set(df_integrated['Reference'].unique())
    except Exception as e:
        logging.error(f"Error reading CSV: {e}")
        return []
        
    missing = list(all_refs - recovered_refs)
    logging.info(f"Total References: {len(all_refs)}")
    logging.info(f"Already Recovered: {len(recovered_refs)}")
    logging.info(f"Missing (To Search): {len(missing)}")
    return missing

def get_synonyms(dbp_list):
    cache = {}
    if os.path.exists(PUBCHEM_CACHE):
        with open(PUBCHEM_CACHE, 'r') as f:
            cache = json.load(f)
            
    synonym_map = {}
    for dbp in dbp_list:
        syns = [dbp] # Start with the name itself
        if dbp in cache:
            # Add pubchem synonyms, filtered for length > 3 to avoid noise
            # And strict string cleaning
            pc_syns = cache[dbp].get('synonyms', [])
            for s in pc_syns:
                if len(s) > 3:
                    syns.append(s)
        synonym_map[dbp] = list(set(syns)) # Unique
    return synonym_map

def main():
    # 1. Connect to DB
    if not os.path.exists(LANCEDB_URI):
        logging.error(f"DB not found at {LANCEDB_URI}")
        return

    logging.info(f"Connecting to LanceDB at {LANCEDB_URI}...")
    db = lancedb.connect(LANCEDB_URI)
    if TABLE_NAME not in db.table_names():
        logging.error(f"Table {TABLE_NAME} not found.")
        return
    tbl = db.open_table(TABLE_NAME)
    logging.info(f"Table loaded. Rows: {tbl.count_rows()}")

    # 2. Prepare Queries
    missing_dbps = load_missing_dbps()
    if not missing_dbps:
        logging.info("No missing DBPs.")
        return
        
    synonym_map = get_synonyms(missing_dbps)
    
    results = []
    
    # 3. Search Loop
    # We use FTS. Queries must be escaped correctly.
    # We will search one synonym at a time to be safe/granular, or batch OR if robust.
    # Tantivy query parser can be tricky with special chars.
    # Safest: Search exact phrase using quotes.
    
    print("Searching...")
    for dbp in tqdm(missing_dbps):
        found = False
        found_via = None
        doc_found = None
        
        # Prioritize original name
        names_to_check = synonym_map.get(dbp, [dbp])
        # Sort: Original first, then longest synonyms (more specific)
        names_to_check.sort(key=len, reverse=True)
        # Ensure original is checked if lost in sort
        if dbp in names_to_check:
            names_to_check.remove(dbp)
            names_to_check.insert(0, dbp)
            
        # Limit to top 20 synonyms to avoid infinite loops
        names_to_check = names_to_check[:20]
        
        for name in names_to_check:
            # Escape quotes in name
            safe_name = name.replace('"', '\\"')
            query = f'"{safe_name}"' # Exact phrase search
            
            try:
                # Limit 1 is sufficient to prove presence
                res = tbl.search(query).limit(1).to_pandas()
                if not res.empty:
                    found = True
                    found_via = name
                    doc_found = res.iloc[0]['doc_id']
                    break
            except Exception as e:
                # FTS might fail on weird chars
                # logging.warning(f"Search error for {name}: {e}")
                pass
        
        results.append({
            "IUPAC name": dbp,
            "Found In Offline DB": found,
            "Found Via": found_via,
            "Document ID": doc_found
        })
        
    # 4. Save and Summarize
    df_res = pd.DataFrame(results)
    df_res.to_csv(OUTPUT_CSV, index=False)
    
    found_count = df_res['Found In Offline DB'].sum()
    total = len(df_res)
    
    logging.info("-" * 30)
    logging.info(f"Search Scope: Full Offline DB ({LANCEDB_URI})")
    logging.info(f"Total Searched: {total}")
    logging.info(f"Found in DB (Recovery): {found_count}")
    logging.info(f"Still Absent: {total - found_count}")
    logging.info(f"Recovery Rate: {found_count/total:.1%}")
    logging.info("-" * 30)

if __name__ == "__main__":
    main()
