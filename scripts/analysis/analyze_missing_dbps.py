
import pandas as pd
import os
import logging
import subprocess
import glob

# Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')

EXCEL_PATH = 'es4c13900_si_001.xlsx'
INTEGRATED_CSV = 'integrated_normalization_mapping.csv'
CORPUS_DIR = 'agent/searching_results/e2e_run_20260125_130247/literature_searching'
PATTERN_FILE = 'missing_dbps_patterns.txt'

def main():
    # 1. Load All Reference DBPs
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
        return

    # 2. Load Recovered DBPs
    try:
        df_integrated = pd.read_csv(INTEGRATED_CSV)
        recovered_refs = set(df_integrated['Reference'].unique())
    except Exception as e:
        logging.error(f"Error reading CSV: {e}")
        return
        
    # 3. Identify Missing
    missing_refs = list(all_refs - recovered_refs)
    total_missing = len(missing_refs)
    logging.info(f"Total References: {len(all_refs)}")
    logging.info(f"Total Recovered: {len(recovered_refs)}")
    logging.info(f"Total Missing: {total_missing}")
    
    if total_missing == 0:
        logging.info("No missing DBPs to analyze.")
        return

    # 4. Batch Search using Grep
    logging.info(f"Preparing batch search for {total_missing} DBPs...")
    
    # Write patterns to file
    with open(PATTERN_FILE, 'w') as f:
        for ref in missing_refs:
            # Escape regex special chars if we were using -E, but -F handles fixed strings
            # However, newlines in strings could break things, but DBPs shouldn't have them.
            f.write(f"{ref}\n")
            
    logging.info(f"Saved patterns to {PATTERN_FILE}")
    logging.info(f"Running grep -F -f across corpus (may take a minute)...")
    
    # Run grep
    # -i: case insensitive
    # -F: fixed string search (fast)
    # -f: read patterns from file
    # -r: recursive
    # -l: print filename only (sufficient to know it exists), OR
    # just output the matching line. We need to know WHICH pattern matched.
    # grep -o -F -f pattern_file -r dir
    # -o outputs only the matched part, which helps identify the DBP.
    
    cmd = ['grep', '-r', '-i', '-o', '-F', '-f', PATTERN_FILE, CORPUS_DIR]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        # Output format: filename:match
        # e.g. dir/file.json:Trichloromethane
        
        found_in_corpus = set()
        
        # Parse output
        # Optimizing: we only need to know if it appeared AT ALL.
        # But grep might return distinct capitalized versions. 
        # We need to map back to our missing_refs list (which is case sensitive in python set, but we searched case-insensitive)
        
        match_lines = result.stdout.strip().split('\n')
        logging.info(f"Grep finished. Processing {len(match_lines)} matches...")
        
        # Create a lowercase map for robust checking
        # ref_lower -> original_ref
        ref_map = {r.lower(): r for r in missing_refs}
        
        for line in match_lines:
            if not line: continue
            # Split filename:match
            # file path may contain colons? unlikely in this OS.
            parts = line.split(':', 1)
            if len(parts) < 2: continue
            
            match_str = parts[1].strip().lower()
            
            # Use strict mapping to ensure what we found is actually in our missing list
            if match_str in ref_map:
                found_in_corpus.add(ref_map[match_str])
        
        # Categorize
        actually_present = len(found_in_corpus)
        truly_absent = total_missing - actually_present
        
        logging.info("-" * 40)
        logging.info(f"Systematic Gap Analysis (N={total_missing})")
        logging.info("-" * 40)
        logging.info(f"Absent from Corpus (Corpus Mismatch): {truly_absent} ({truly_absent/total_missing:.1%})")
        logging.info(f"Present but Missed (Recall Error):    {actually_present} ({actually_present/total_missing:.1%})")
        logging.info("-" * 40)
        
        # Adjusted Recall Calculation
        # Adjusted Recall = Recovered / (Total Refs - Absent)
        # We recovered len(recovered_refs)
        # The 'Addressable' set is Total - truly_absent
        
        addressable_refs = len(all_refs) - truly_absent
        adjusted_recall = len(recovered_refs) / addressable_refs
        
        logging.info(f"Total Recovered: {len(recovered_refs)}")
        logging.info(f"Total Addressable (Present in Corpus): {addressable_refs}")
        logging.info(f"Adjusted System Recall: {adjusted_recall:.2%}")
        
    except Exception as e:
        logging.error(f"Grep failed: {e}")
    finally:
        if os.path.exists(PATTERN_FILE):
             os.remove(PATTERN_FILE)

if __name__ == "__main__":
    main()
