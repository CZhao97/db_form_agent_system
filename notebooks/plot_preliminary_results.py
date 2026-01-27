
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import os
from sklearn.metrics import confusion_matrix, classification_report
import re

# Set style
sns.set_theme(style="whitegrid")
OUT_DIR = "notebooks/eval_plots"
os.makedirs(OUT_DIR, exist_ok=True)

CSV_PATH = "evaluation_results_new.csv"

def extract_label(text):
    if not isinstance(text, str):
        return "Error/Empty"
    text = text.lower()
    if "not confirmed" in text:
        return "Not Confirmed"
    if "confirmed dbp" in text or "confirmed" in text: # Order matters: check "not" first
        return "Confirmed"
    if "unclear" in text or "cannot" in text:
        return "Unclear"
    return "Other"

def main():
    print(f"Loading {CSV_PATH}...")
    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return

    print(f"Total Rows: {len(df)}")
    
    # 1. Clean Labels
    # Agent Label
    if 'normalized_prediction' not in df.columns:
        print("Column 'normalized_prediction' missing!")
        return

    # Agent Label Mapping
    def map_agent_label(x):
        x = str(x).lower().strip()
        if "yes" in x or "confirmed" in x and "not" not in x: return "Confirmed"
        if "no" in x and "not" not in x and "formation" not in x: return "Not Confirmed"  # "No"
        if "not confirmed" in x: return "Not Confirmed"
        if "unclear" in x: return "Unclear"
        if "error" in x: return "Error"
        return "Other"

    # Use 'normalized_prediction' if 'agent_verdict' is weird, but 'agent_verdict' seems to have the raw text.
    # The normalization in the main script might be imperfect.
    # Let's use 'normalized_prediction' but if it is 'Unclear' and verdict says 'Not Confirmed', fix it.
    
    def intelligent_label(row):
        norm = str(row.get('normalized_prediction', '')).lower()
        verdict = str(row.get('agent_verdict', '')).lower()
        
        # Priority 1: Clear normalization
        if norm == 'yes': return "Confirmed"
        if norm == 'no': return "Not Confirmed"
        
        # Priority 2: Verdict Text Fallback
        if "not confirmed" in verdict: return "Not Confirmed"
        if "confirmed" in verdict and "not" not in verdict: return "Confirmed"
        if "unclear" in verdict: return "Unclear"
        
        return "Unclear"

    df['Agent_Label'] = df.apply(intelligent_label, axis=1)
    
    # Ground Truth cleaning
    # Model Prediction often has extra text.
    df['Ref_Label'] = df['Model Prediction'].apply(extract_label)

    # Filter out weird ones
    valid_labels = ["Confirmed", "Not Confirmed", "Unclear"]
    df_plot = df[df['Agent_Label'].isin(valid_labels) & df['Ref_Label'].isin(valid_labels)].copy()
    
    print(f"Valid Rows for Comparison: {len(df_plot)} / {len(df)}")
    
    # ---------------- PLOT 1: Verdict Distribution ----------------
    plt.figure(figsize=(8, 6))
    ax = sns.countplot(data=df, x='Agent_Label', order=["Confirmed", "Not Confirmed", "Unclear", "Error"])
    plt.title("Agent Verdict Distribution (Preliminary)")
    plt.xlabel("Verdict")
    plt.ylabel("Count")
    for container in ax.containers:
        ax.bar_label(container)
    plt.savefig(f"{OUT_DIR}/verdict_distribution.png")
    plt.close()
    print("Saved verdict_distribution.png")

    # ---------------- PLOT 2: Confusion Matrix ----------------
    if len(df_plot) > 0:
        labels = ["Confirmed", "Not Confirmed", "Unclear"]
        cm = confusion_matrix(df_plot['Ref_Label'], df_plot['Agent_Label'], labels=labels)
        
        plt.figure(figsize=(8, 6))
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=labels, yticklabels=labels)
        plt.title("Confusion Matrix: Agent vs Reference")
        plt.xlabel("Agent Verdict")
        plt.ylabel("Reference (Model Pred)")
        plt.savefig(f"{OUT_DIR}/confusion_matrix.png")
        plt.close()
        print("Saved confusion_matrix.png")
        
        # Print metrics
        print("\nClassification Report:")
        print(classification_report(df_plot['Ref_Label'], df_plot['Agent_Label'], labels=labels))

    # ---------------- PLOT 3: Error Rate Over Time (Session) ----------------
    # Inferred from row order
    df['Cumulative_Error'] = (df['Agent_Label'] == "Error").cumsum()
    
    plt.figure(figsize=(10, 5))
    plt.plot(df.index, df['Cumulative_Error'], label="Cumulative Errors")
    plt.title("Run Stability: Cumulative Errors Over Processed items")
    plt.xlabel("Item Index")
    plt.ylabel("Total Errors")
    plt.legend()
    plt.savefig(f"{OUT_DIR}/run_stability.png")
    plt.close()
    print("Saved run_stability.png")

if __name__ == "__main__":
    main()
