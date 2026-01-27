
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

BASELINE_PATH = "notebooks/dbp_gemini_flash_2_5_results.xlsx"
AGENT_PATH = "evaluation_results_new.csv"
OUT_DIR = "notebooks/eval_plots"
os.makedirs(OUT_DIR, exist_ok=True)

def normalize_verdict(text):
    if not isinstance(text, str): return "Unclear"
    text = text.lower().strip()
    if "yes" in text or ("confirmed" in text and "not" not in text): return "Confirmed"
    if "no" in text or "not confirmed" in text: return "Not Confirmed"
    return "Unclear"

def main():
    print(f"Loading Baseline: {BASELINE_PATH}")
    try:
        df_base = pd.read_excel(BASELINE_PATH)
    except Exception as e:
        print(f"Error loading baseline: {e}")
        return

    print(f"Loading Agent: {AGENT_PATH}")
    try:
        df_agent = pd.read_csv(AGENT_PATH)
    except Exception as e:
        print(f"Error loading agent: {e}")
        return
        
    # 1. Prepare Baseline
    # Key: 'IUPAC name'
    # Verdict: 'Model Prediction'
    df_base['Baseline_Verdict'] = df_base['Model Prediction'].apply(normalize_verdict)
    df_base_clean = df_base[['IUPAC name', 'Baseline_Verdict']].dropna(subset=['IUPAC name']).drop_duplicates(subset=['IUPAC name'])
    
    # 2. Prepare Agent
    # Key: 'input_compound' (matches IUPAC name)
    # Verdict: 'normalized_prediction' or 'agent_verdict'
    
    # Intelligent normalization logic from before
    def intelligent_label(row):
        norm = str(row.get('normalized_prediction', '')).lower()
        verdict = str(row.get('agent_verdict', '')).lower()
        if norm == 'yes': return "Confirmed"
        if norm == 'no': return "Not Confirmed"
        if "not confirmed" in verdict: return "Not Confirmed"
        if "confirmed" in verdict and "not" not in verdict: return "Confirmed"
        return "Unclear"

    df_agent['Agent_Verdict'] = df_agent.apply(intelligent_label, axis=1)
    df_agent_clean = df_agent[['input_compound', 'Agent_Verdict']].dropna(subset=['input_compound'])
    
    # Handle duplicates in Agent results (take most recent or best?)
    # Users usually care about the final result. If we have multiple, let's take the one that is NOT Unclear if possible, or just the last one.
    # Logic: Group by compound, take last.
    df_agent_final = df_agent_clean.groupby('input_compound').last().reset_index()
    
    # 3. Merge
    # Inner join to compare on the same set
    merged = pd.merge(df_base_clean, df_agent_final, left_on='IUPAC name', right_on='input_compound', how='inner')
    
    print(f"Intersection Size: {len(merged)} compounds")
    
    if len(merged) == 0:
        print("No intersection found! Checking name formats...")
        print("Base sample:", df_base_clean['IUPAC name'].head().tolist())
        print("Agent sample:", df_agent_final['input_compound'].head().tolist())
        return

    # 4. Calculate Recall
    # Ground Truth is assumed to be ALL POSITIVE (since dataset is "Confirmed DBPs")
    # Recall = (Count Confirmed) / Topal Computed
    
    recall_base = (merged['Baseline_Verdict'] == 'Confirmed').mean() * 100
    recall_agent = (merged['Agent_Verdict'] == 'Confirmed').mean() * 100
    
    print(f"Baseline Recall: {recall_base:.2f}%")
    print(f"Hybrid Agent Recall: {recall_agent:.2f}%")
    
    # 5. Plot: Verdict Distribution Comparison (Count)
    
    # Reshape data for plotting: 
    # Create a DataFrame with columns [Compound, System, Verdict]
    plot_data = []
    for _, row in merged.iterrows():
        plot_data.append({'System': 'Baseline (Gemini 2.5)', 'Verdict': row['Baseline_Verdict']})
        plot_data.append({'System': 'Hybrid Agent (Yours)', 'Verdict': row['Agent_Verdict']})
        
    df_plot = pd.DataFrame(plot_data)
    
    plt.figure(figsize=(10, 6))
    
    # Define Verdict Order and Colors
    verdict_order = ["Confirmed", "Not Confirmed", "Unclear"]
    palette = {"Confirmed": "#2ca02c", "Not Confirmed": "#d62728", "Unclear": "#ff7f0e"} # Green, Red, Orange
    
    ax = sns.countplot(data=df_plot, x='System', hue='Verdict', hue_order=verdict_order, palette=palette)
    
    plt.title(f"Verdict Distribution Comparison (N={len(merged)} Compounds)", fontsize=14)
    plt.xlabel("System", fontsize=12)
    plt.ylabel("Count of Compounds", fontsize=12)
    plt.legend(title="Verdict")
    
    # Add count labels
    for container in ax.containers:
        ax.bar_label(container)
    
    out_path = f"{OUT_DIR}/baseline_comparison.png"
    plt.savefig(out_path)
    print(f"Saved comparison plot to {out_path}")
    
    # 6. Detailed stat
    # Overlap analysis
    both_confirmed = ((merged['Baseline_Verdict'] == 'Confirmed') & (merged['Agent_Verdict'] == 'Confirmed')).sum()
    agent_only = ((merged['Baseline_Verdict'] != 'Confirmed') & (merged['Agent_Verdict'] == 'Confirmed')).sum()
    base_only = ((merged['Baseline_Verdict'] == 'Confirmed') & (merged['Agent_Verdict'] != 'Confirmed')).sum()
    both_missed = ((merged['Baseline_Verdict'] != 'Confirmed') & (merged['Agent_Verdict'] != 'Confirmed')).sum()
    
    print("\nOverlap Analysis:")
    print(f"Both Confirmed: {both_confirmed}")
    print(f"Agent Rescued (Base missed): {agent_only}")
    print(f"Base Won (Agent missed): {base_only}")
    print(f"Both Missed: {both_missed}")

if __name__ == "__main__":
    main()
