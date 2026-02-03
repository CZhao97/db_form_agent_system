
import os
import sys
import json
import pandas as pd
import subprocess
import matplotlib.pyplot as plt

def main():
    offline_results_path = "comparison_results_offline_50.csv"
    hybrid_results_path = "comparison_results_hybrid_rescue.csv"
    plot_path = "comparison_offline_vs_hybrid_rescue.png"
    
    print(f"Reading offline results from {offline_results_path}...")
    try:
        df_off = pd.read_csv(offline_results_path)
    except Exception as e:
        print(f"Error reading offline CSV: {e}")
        return

    # Filter for successful rows only (just in case)
    # The CSV might contain partial lines if it crashed, but pandas read_csv usually handles it or errors.
    # We'll assume the rows present are valid.
    print(f"Found {len(df_off)} rows.")
    
    # Create input JSONL for Hybrid
    # We need to re-run exactly these chemicals.
    rescue_input_file = "rescue_hybrid_input.jsonl"
    print(f"Creating {rescue_input_file} for {len(df_off)} queries...")
    
    with open(rescue_input_file, 'w') as f:
        for _, row in df_off.iterrows():
            query = row['query']
            # Escape newlines if any
            if isinstance(query, str):
                json_line = json.dumps({"query": query})
                f.write(json_line + "\n")
            else:
                print(f"Skipping invalid query row: {row}")

    # Run Hybrid
    # Force clean start for hybrid output
    if os.path.exists(hybrid_results_path):
        os.remove(hybrid_results_path)
        
    print("\n---------- STARTING HYBRID RUN (RESCUE) ----------")
    cmd = [
        sys.executable,
        "scripts/evaluate_recovered_samples.py",
        "--input", rescue_input_file,
        "--output", hybrid_results_path,
        "--workers", "8"
    ]
    
    env = os.environ.copy()
    env["INCLUDE_ONLINE_SEARCH"] = "True"
    env["INCLUDE_OFFLINE_SEARCH"] = "True"
    env["CUDA_VISIBLE_DEVICES"] = "1" # User Requested GPU 1
    
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)
    
    # Generate Plot
    print("\nGenerating Comparison Plot...")
    if not os.path.exists(hybrid_results_path):
        print("Hybrid results file not found!")
        return

    df_hyb = pd.read_csv(hybrid_results_path)
    
    # Merge
    # Ensure columns exist
    for df in [df_off, df_hyb]:
        if "normalized_prediction" not in df.columns:
            df["normalized_prediction"] = "Error"
            
    # Clean names
    df_off = df_off.rename(columns={"normalized_prediction": "Offline Prediction", "agent_verdict": "Offline Verdict"})
    df_hyb = df_hyb.rename(columns={"normalized_prediction": "Hybrid Prediction", "agent_verdict": "Hybrid Verdict"})
    
    # Merge on chemical_name
    merged = pd.merge(
        df_off[["chemical_name", "Offline Prediction", "Offline Verdict"]],
        df_hyb[["chemical_name", "Hybrid Prediction", "Hybrid Verdict"]],
        on="chemical_name",
        how="inner"
    )
    
    print(f"Merged {len(merged)} paired results.")
    
    # Calculate Agreement
    merged["Agreement"] = merged["Offline Prediction"] == merged["Hybrid Prediction"]
    agreement_rate = merged["Agreement"].mean()
    print(f"Agreement Rate: {agreement_rate:.2%}")
    
    # Plot Usage
    valid_outcomes = ["Yes", "No", "Unclear", "Error"]
    def normalize(x):
        x = str(x).strip()
        if x in valid_outcomes: return x
        if "Yes" in x: return "Yes"
        if "No" in x: return "No"
        return "Unclear"

    merged["Offline Prediction"] = merged["Offline Prediction"].apply(normalize)
    merged["Hybrid Prediction"] = merged["Hybrid Prediction"].apply(normalize)
    
    off_counts = merged["Offline Prediction"].value_counts().reindex(valid_outcomes, fill_value=0)
    hyb_counts = merged["Hybrid Prediction"].value_counts().reindex(valid_outcomes, fill_value=0)
    
    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(valid_outcomes))
    width = 0.35
    
    ax.bar([i - width/2 for i in x], off_counts, width, label='Offline Only')
    ax.bar([i + width/2 for i in x], hyb_counts, width, label='Hybrid')
    
    ax.set_ylabel('Count')
    ax.set_title(f'Offline vs Hybrid Verdict (N={len(merged)})')
    ax.set_xticks(x)
    ax.set_xticklabels(valid_outcomes)
    ax.legend()
    
    plt.tight_layout()
    plt.savefig(plot_path)
    print(f"Plot saved to {plot_path}")
    
    # Save CSV
    merged.to_csv(plot_path.replace(".png", ".csv"), index=False)

if __name__ == "__main__":
    main()
