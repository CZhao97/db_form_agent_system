
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

def analyze_results(file_path):
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return

    print(f"Loading results from {file_path}...")
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    print(f"Total rows: {len(df)}")
    
    # Check for required columns
    required_cols = ['agent_verdict', 'Model Prediction']
    for col in required_cols:
        if col not in df.columns:
            print(f"Warning: Column '{col}' not found. Available: {df.columns.tolist()}")
    
    # Normalize Agent Verdicts
    # "Confirmed DBP" -> Yes
    # "Not Confirmed DBP" -> No
    # Others -> Unclear
    
    def normalize_verdict(v):
        v = str(v).lower()
        if "not confirmed" in v:
            return "Not Confirmed DBP"
        if "confirmed" in v and "not" not in v:
             return "Confirmed DBP"
        
        return "Unclear"

    # Normalize Agent
    # We must ensure robust handling. 
    df['Agent_Normalized'] = df['agent_verdict'].apply(normalize_verdict)
    
    # Normalize Baseline if present
    if 'Model Prediction' in df.columns:
        df['Baseline_Normalized'] = df['Model Prediction'].apply(normalize_verdict)

    # --- Statistics ---
    print("\n--- Agent Results Distribution ---")
    agent_counts = df['Agent_Normalized'].value_counts()
    print(agent_counts)
    
    if len(df) > 0:
        recall = agent_counts.get('Confirmed DBP', 0) / len(df) * 100
        print(f"\nAgent Recall (Sensitivity): {recall:.1f}%")

    if 'Baseline_Normalized' in df.columns:
        print("\n--- Baseline Results Distribution ---")
        baseline_counts = df['Baseline_Normalized'].value_counts()
        print(baseline_counts)
        if len(df) > 0:
            b_recall = baseline_counts.get('Confirmed DBP', 0) / len(df) * 100
            print(f"Baseline Recall (Sensitivity): {b_recall:.1f}%")

    # --- Plotting ---
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    # Agent Plot
    sns.countplot(y='Agent_Normalized', data=df, ax=axes[0], order=['Confirmed DBP', 'Not Confirmed DBP', 'Unclear'])
    axes[0].set_title('Agent Verdicts')
    axes[0].set_xlabel('Count')
    
    # Comparisons
    if 'Baseline_Normalized' in df.columns:
        # Side-by-side bar chart
        comparison_data = []
        for cat in ['Confirmed DBP', 'Not Confirmed DBP', 'Unclear']:
            comparison_data.append({'Model': 'Baseline', 'Verdict': cat, 'Count': baseline_counts.get(cat, 0)})
            comparison_data.append({'Model': 'Agent', 'Verdict': cat, 'Count': agent_counts.get(cat, 0)})
        
        comp_df = pd.DataFrame(comparison_data)
        sns.barplot(x='Verdict', y='Count', hue='Model', data=comp_df, ax=axes[1])
        axes[1].set_title('Agent vs Baseline Performance')
    
    plt.tight_layout()
    plot_file = "agent_vs_baseline_analysis.png"
    plt.savefig(plot_file)
    print(f"\nPlot saved to {plot_file}")

if __name__ == "__main__":
    # Look for the file in the current directory or parent
    target_file = "evaluation_results_new.csv"
    if not os.path.exists(target_file):
        # Try full path if running from notebook dir or root
        guesses = [
            "/home/chen/GNPS_SIM/agent/db_form_agent_system/evaluation_results_new.csv",
            "../evaluation_results_new.csv"
        ]
        for g in guesses:
            if os.path.exists(g):
                target_file = g
                break
                
    analyze_results(target_file)
