import json
import pandas as pd
import sys
import os
import matplotlib.pyplot as plt
from flair.data import Sentence
from flair.nn import Classifier
from flair.models import EntityMentionLinker

# Constants
EXCEL_PATH = 'es4c13900_si_001.xlsx'
JSON_PATH = 'agent/searching_results/e2e_run_20260125_130247/literature_searching/ner_results/chemical_ner_results.json'
# Using the path confirmed to work
LINKER_PATH = '/home/chen/.flair/models/biosyn-sapbert-bc5cdr-chemical-no-ab3p/models--hunflair--biosyn-sapbert-bc5cdr-chemical-no-ab3p/snapshots/2929796c7af2316d3ae17447780487e5a86a2e8e/pytorch_model.bin'
OUTPUT_PLOT = 'dbp_coverage_plot_normalized.png'
OUTPUT_CSV = 'dbp_normalization_mapping.csv'
BATCH_SIZE = 32

def main():
    # 1. Load Excel DBPs
    print(f"Loading {EXCEL_PATH}...")
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=1)
        if 'IUPAC name' not in df.columns:
             # Fallback
             df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=0)
             if 'IUPAC name' in df.iloc[0].values:
                 df.columns = df.iloc[0]
                 df = df[1:]
        
        # Get unique names
        dbp_list = df['IUPAC name'].dropna().astype(str).unique().tolist()
        print(f"Total unique reference DBPs in Excel: {len(dbp_list)}")
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    # 2. Load Models
    print("Loading Hunflair2 NER...")
    try:
        ner = Classifier.load('hunflair2')
    except Exception as e:
        print(f"Error loading NER: {e}")
        return

    print(f"Loading Linker from {LINKER_PATH}...")
    try:
        linker = EntityMentionLinker.load(LINKER_PATH)
    except Exception as e:
        print(f"Error loading linker: {e}")
        return

    # 3. Normalize DBPs (Batch Processing)
    print(f"Normalizing DBPs to MeSH IDs (Batch Size: {BATCH_SIZE})...")
    
    # Create Sentences
    sentences = [Sentence(name) for name in dbp_list]
    
    # Run NER
    print("Running NER inference...")
    # Using mini_batch_size to speed up
    ner.predict(sentences, mini_batch_size=BATCH_SIZE, verbose=True)
    
    # Run Linker
    print("Running Linker inference...")
    linker.predict(sentences)
    
    # Extract Results
    mapping_results = []
    mapped_count = 0
    
    for i, sentence in enumerate(sentences):
        dbp_name = dbp_list[i]
        
        # Extract best MeSH ID from ALL entities found in the sentence
        mesh_id = None
        best_score = -1.0
        
        for entity in sentence.get_spans('ner'):
            for label in entity.labels:
                val = label.value
                if val.startswith("MESH:"):
                    if label.score > best_score:
                        mesh_id = val
                        best_score = label.score
        
        if mesh_id:
            mapped_count += 1
            
        mapping_results.append({'original_name': dbp_name, 'mesh_id': mesh_id})

    # Save mapping for inspection
    pd.DataFrame(mapping_results).to_csv(OUTPUT_CSV, index=False)
    print(f"Saved normalization mapping to {OUTPUT_CSV}")

    # 4. Compare with NER Results
    print(f"Loading {JSON_PATH}...")
    try:
        with open(JSON_PATH, 'r') as f:
            ner_data = json.load(f)
            found_mesh_ids = set(ner_data.keys())
            
            # Also check per_file_results just in case
            if 'per_file_results' in ner_data:
                for res in ner_data['per_file_results']:
                    if 'entities' in res:
                        found_mesh_ids.update(res['entities'].keys())
    except Exception as e:
        print(f"Error reading JSON: {e}")
        return

    print(f"Total unique MeSH IDs in NER results: {len(found_mesh_ids)}")

    # Calculate Overlap
    matched_count = 0
    unique_mesh_ids_mapped = set()
    
    # Count how many REFERENCES are recovered (via ID match)
    # The user asked: "map 687 dbps to meth id. then calculate the overlap"
    # Overlap usually means "How many of the 687 DBPs map to an ID that is in the found list?"
    
    for item in mapping_results:
        mid = item['mesh_id']
        if mid and mid in found_mesh_ids:
            matched_count += 1
    
    total_refs = len(dbp_list)
    
    print("-" * 30)
    print(f"Total Reference DBPs: {total_refs}")
    print(f"Successfully Normalized to MeSH: {mapped_count} ({mapped_count/total_refs*100:.1f}%)")
    print(f"Found in Literature (via MeSH overlap): {matched_count}")
    print(f"Percentage Recovered: {matched_count / total_refs * 100:.2f}%")
    print("-" * 30)

    # 5. Plot
    labels = [f'Recovered ({matched_count})', f'Not Found ({total_refs - matched_count})']
    sizes = [matched_count, total_refs - matched_count]
    colors = ['#66b3ff', '#ff9999'] 
    explode = (0.1, 0)

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, text, autotext = ax.pie(sizes, explode=explode, labels=labels, colors=colors, 
                                    autopct='%1.1f%%', shadow=True, startangle=140,
                                    textprops=dict(color="black"))
    
    plt.setp(autotext, size=12, weight="bold")
    plt.setp(text, size=12)
    
    ax.axis('equal')  
    plt.title(f"Coverage of Reference DBPs (Total: {total_refs})\nby Literature NER (Normalized via Hunflair2)", fontsize=14)
    
    plt.savefig(OUTPUT_PLOT, dpi=300, bbox_inches='tight')
    print(f"Plot saved to {OUTPUT_PLOT}")

if __name__ == "__main__":
    main()
