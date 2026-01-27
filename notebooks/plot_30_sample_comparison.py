
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

# File Paths
SAMPLE_PATH = "notebooks/dbp_evaluation_sample_results.csv" # Online Only
BASELINE_PATH = "notebooks/dbp_gemini_flash_2_5_results.xlsx" # Baseline
HYBRID_PATH = "evaluation_results_new.csv" # Hybrid (Flawed)

OUT_DIR = "notebooks/eval_plots"
os.makedirs(OUT_DIR, exist_ok=True)

def normalize_verdict(text):
    if not isinstance(text, str): return "Unclear"
    text = text.lower().strip()
    if "yes" in text or ("confirmed" in text and "not" not in text): return "Confirmed"
    if "no" in text or "not confirmed" in text: return "Not Confirmed"
    if "unclear" in text: return "Unclear"
    return "Other"

def main():
    print("Loading datasets...")
    # 1. Load Sample (The Anchor Set)
    try:
        df_sample = pd.read_csv(SAMPLE_PATH)
        target_compounds = df_sample['compound'].unique()
        print(f"Target Set: {len(target_compounds)} compounds from Sample.")
    except Exception as e:
        print(f"Error loading sample: {e}")
        return

    # 2. Load Baseline
    try:
        df_base = pd.read_excel(BASELINE_PATH)
    except Exception as e:
        print(f"Error loading baseline: {e}")
        return

    # 3. Load Hybrid
    try:
        df_hybrid = pd.read_csv(HYBRID_PATH)
    except Exception as e:
        print(f"Error loading hybrid: {e}")
        return

    # --- Data Prep ---
    results = []

    for compound in target_compounds:
        # A. Baseline Retrieval
        base_row = df_base[df_base['IUPAC name'] == compound]
        if not base_row.empty:
            base_verdict = normalize_verdict(base_row.iloc[0]['Model Prediction'])
        else:
            base_verdict = "Missing"

        # B. Online Sample Retrieval
        sample_row = df_sample[df_sample['compound'] == compound]
        if not sample_row.empty:
            # Use predicted_normalized column directly if available and reliable
            sample_verdict = normalize_verdict(sample_row.iloc[0]['predicted_normalized'])
        else:
            sample_verdict = "Missing"

        # C. Hybrid Retrieval
        # Use input_compound to match
        hybrid_row = df_hybrid[df_hybrid['input_compound'] == compound]
        if not hybrid_row.empty:
            # Take the last entry if duplicates exist
            hybrid_verdict = normalize_verdict(hybrid_row.iloc[-1]['normalized_prediction'])
        else:
            hybrid_verdict = "Missing" # Or Unclear

        # Append
        results.append({'System': 'Baseline (Gemini 2.5)', 'Verdict': base_verdict})
        results.append({'System': 'Online Only (Sample)', 'Verdict': sample_verdict})
        results.append({'System': 'Hybrid (No Rerank)', 'Verdict': hybrid_verdict})

    df_plot = pd.DataFrame(results)
    
    # Filter out missing
    df_plot = df_plot[df_plot['Verdict'] != 'Missing']

    # --- Plotting ---
    plt.figure(figsize=(10, 6))
    
    # Define Verdict Order and Colors
    verdict_order = ["Confirmed", "Not Confirmed", "Unclear"]
    palette = {"Confirmed": "#2ca02c", "Not Confirmed": "#d62728", "Unclear": "#ff7f0e", "Other": "gray"}
    
    ax = sns.countplot(data=df_plot, x='System', hue='Verdict', hue_order=verdict_order, palette=palette)
    
    plt.title(f"Comparison on 30 Sample Compounds\nImpact of Reranker Absence in Hybrid Run", fontsize=14)
    plt.xlabel("System / Configuration", fontsize=12)
    plt.ylabel("Count of Compounds", fontsize=12)
    plt.legend(title="Agent Verdict")
    
    # Add count labels
    for container in ax.containers:
        ax.bar_label(container)

    out_path = f"{OUT_DIR}/sample_30_comparison.png"
    plt.savefig(out_path)
    print(f"Plot saved to {out_path}")

if __name__ == "__main__":
    main()
