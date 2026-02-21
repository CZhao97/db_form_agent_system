
import json
import pandas as pd
import os
import matplotlib.pyplot as plt
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
EXCEL_PATH = 'es4c13900_si_001.xlsx'
JSON_PATH = '/home/chen/GNPS_SIM/agent/searching_results/run_20260218_230426/ner_results/chemical_ner_results.json'
PUBCHEM_CACHE = 'pubchem_synonym_cache.json'
LLM_MAPPING_CSV = 'llm_normalization_mapping.csv'
OUTPUT_PLOT = 'dbp_coverage_waterfall.png'
OUTPUT_CSV = 'integrated_normalization_mapping.csv'

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
        return [], set()

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
        return [], set()
        
    return reference_dbps, found_names

def main():
    refs, found_names_set = load_data()
    if not refs: return
    
    # Track results
    final_mapping = []
    recovered_refs = set()
    
    # --- Step 1: Exact Match ---
    count_exact = 0
    for ref in refs:
        if ref.lower() in found_names_set:
            final_mapping.append({"Reference": ref, "Method": "Exact", "Candidate": ref})
            recovered_refs.add(ref)
            count_exact += 1
            
    logging.info(f"Step 1 (Exact): {count_exact} matches")

    # --- Step 2: PubChem Synonyms ---
    count_pubchem = 0
    
    # Load Cache
    pc_cache = {}
    if os.path.exists(PUBCHEM_CACHE):
        with open(PUBCHEM_CACHE, 'r') as f:
            pc_cache = json.load(f)

    for ref in refs:
        if ref in recovered_refs: continue
        
        # Check cache
        if ref in pc_cache:
            syns = pc_cache[ref].get('synonyms', [])
            matched_syn = None
            for s in syns:
                if s in found_names_set:
                    matched_syn = s
                    break
            
            if matched_syn:
                final_mapping.append({"Reference": ref, "Method": "PubChem", "Candidate": matched_syn})
                recovered_refs.add(ref)
                count_pubchem += 1

    logging.info(f"Step 2 (+PubChem): {count_pubchem} new matches")

    # --- Step 3: LLM Verified ---
    count_llm = 0
    
    if os.path.exists(LLM_MAPPING_CSV):
        llm_df = pd.read_csv(LLM_MAPPING_CSV)
        # Filter for verified matches that are NOT already recovered
        # The CSV likely has 'Type' column. We check 'Match' or similar. 
        # Actually in previous step we saved `calc_llm_normalization_coverage.py` output. 
        # It had columns like "Reference", "Type" (exact/llm_verified), "Candidate".
        
        for _, row in llm_df.iterrows():
            ref = row['Reference']
            match_type = row.get('Type', '')
            candidate = row.get('Candidate', '')
            
            if ref not in recovered_refs and match_type == 'llm_verified':
                final_mapping.append({"Reference": ref, "Method": "LLM", "Candidate": candidate})
                recovered_refs.add(ref)
                count_llm += 1
                
    logging.info(f"Step 3 (+LLM): {count_llm} new matches")

    # --- Summary ---
    total = len(refs)
    total_recovered = len(recovered_refs)
    missing = total - total_recovered
    
    logging.info(f"Total Recovered: {total_recovered}/{total} ({total_recovered/total:.2%})")
    
    # Save CSV
    pd.DataFrame(final_mapping).to_csv(OUTPUT_CSV, index=False)
    
    # --- Waterfall Plot ---
    # Categories: Exact, PubChem, LLM, Remaining
    categories = ['Exact Match', '+ PubChem', '+ LLM', 'Remaining']
    values = [count_exact, count_pubchem, count_llm, missing]
    
    # Cumulative for waterfall
    # Bar 1: Exact (starts 0)
    # Bar 2: PubChem (starts at Exact)
    # Bar 3: LLM (starts at Exact+PubChem)
    # Bar 4: Remaining (starts at Exact+PubChem+LLM, goes to Total? Or just distinct bar?)
    # Better: Stacked Bar with distinct colors
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Bar top positions
    base = 0
    p1 = ax.bar('Normalization', count_exact, label='Exact Match', color='#2ca02c')
    base += count_exact
    
    p2 = ax.bar('Normalization', count_pubchem, bottom=base, label='PubChem Synonym', color='#1f77b4')
    base += count_pubchem
    
    p3 = ax.bar('Normalization', count_llm, bottom=base, label='LLM Verification', color='#ff7f0e')
    base += count_llm
    
    # Add labels
    ax.bar_label(p1, label_type='center', color='white', fontweight='bold')
    if count_pubchem > 0: ax.bar_label(p2, label_type='center', color='white', fontweight='bold')
    if count_llm > 0: ax.bar_label(p3, label_type='center', color='white', fontweight='bold')
    
    # Add Total Bar annotation
    ax.text(0, base + 5, f"Total Recovered: {total_recovered}\n({total_recovered/total:.1%})", 
            ha='center', va='bottom', fontsize=12, fontweight='bold')
            
    # Add Missing Bar next to it for context?
    # Or just one stacked bar.
    
    # Let's do a clearer view: 2 Bars. 
    # Bar 1: Recovered (Stacked)
    # Bar 2: Total (Reference)
    
    # Reset plot for better visualization
    plt.clf()
    fig, ax = plt.subplots(figsize=(8, 6))
    
    x = ['Coverage']
    
    # Stacked components
    b1 = ax.bar(x, count_exact, color='#4CAF50', label='Exact Match')
    b2 = ax.bar(x, count_pubchem, bottom=count_exact, color='#2196F3', label='PubChem Synonym')
    b3 = ax.bar(x, count_llm, bottom=count_exact+count_pubchem, color='#FF9800', label='LLM Verified')
    b4 = ax.bar(x, missing, bottom=count_exact+count_pubchem+count_llm, color='#E0E0E0', label='Not Found', hatch='//')
    
    # Labels
    for b in [b1, b2, b3, b4]:
        ax.bar_label(b, label_type='center', fmt='%d')
        
    plt.title(f"Evaluation of Normalization Strategies (N={total})", fontsize=14)
    plt.ylabel("Number of DBPs")
    plt.legend(loc='upper right', bbox_to_anchor=(1.3, 1))
    
    plt.tight_layout()
    plt.savefig(OUTPUT_PLOT)
    logging.info(f"Plot saved to {OUTPUT_PLOT}")

if __name__ == "__main__":
    main()
