import matplotlib.pyplot as plt
import pandas as pd
import json
import os

# Data (Passed from previous analysis or re-calculated)
# For robustness, we re-calculate or just hardcode the numbers if the previous step was definitive.
# But let's verify quickly to be safe.

EXCEL_PATH = 'es4c13900_si_001.xlsx'
JSON_PATH = 'agent/searching_results/e2e_run_20260125_130247/literature_searching/ner_results/chemical_ner_results.json'
OUTPUT_PLOT = 'dbp_coverage_plot.png'

def main():
    # 1. Load Excel DBPs
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=1)
        if 'IUPAC name' not in df.columns:
             # Fallback
             df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=0)
             if 'IUPAC name' in df.iloc[0].values:
                 df.columns = df.iloc[0]
                 df = df[1:]
        
        dbp_list = df['IUPAC name'].dropna().astype(str).tolist()
        dbp_set = set(n.strip().lower() for n in dbp_list)
        total_refs = len(dbp_set)
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    # 2. Load NER Results and count overlap
    found_count = 0
    try:
        with open(JSON_PATH, 'r') as f:
            data = json.load(f)
        
        found_chemicals = set()
        if 'per_file_results' in data:
            for file_res in data['per_file_results']:
                entities = file_res.get('entities', {})
                for entity_id, info in entities.items():
                    mentions = info.get('mentions', [])
                    for m in mentions:
                        if "(Context:" in m:
                            name = m.split("(Context:")[0].strip()
                        else:
                            name = m.strip()
                        if name:
                            found_chemicals.add(name.lower())
        
        intersection = dbp_set.intersection(found_chemicals)
        found_count = len(intersection)
        
    except Exception as e:
        print(f"Error reading JSON: {e}")
        return

    # 3. Plotting
    missing_count = total_refs - found_count
    
    # Pie Chart
    labels = [f'Recovered ({found_count})', f'Not Found ({missing_count})']
    sizes = [found_count, missing_count]
    colors = ['#66b3ff', '#ff9999'] # Light blue, light red
    explode = (0.1, 0)  # explode the 'Recovered' slice

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, text, autotext = ax.pie(sizes, explode=explode, labels=labels, colors=colors, 
                                    autopct='%1.1f%%', shadow=True, startangle=140,
                                    textprops=dict(color="black"))
    
    plt.setp(autotext, size=12, weight="bold")
    plt.setp(text, size=12)
    
    ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.
    plt.title(f"Coverage of Reference DBPs (Total: {total_refs})\nby Literature NER Extraction", fontsize=14)
    
    # Save
    plt.savefig(OUTPUT_PLOT, dpi=300, bbox_inches='tight')
    print(f"Plot saved to {OUTPUT_PLOT}")
    
    print(f"Recovered: {found_count}")
    print(f"Missing: {missing_count}")
    print(f"Total: {total_refs}")

if __name__ == "__main__":
    main()
