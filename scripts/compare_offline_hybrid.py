
import os
import sys
import json
import random
import subprocess
import pandas as pd
import matplotlib.pyplot as plt
import argparse

def sample_queries(input_file, output_file, n=50, seed=42):
    print(f"Sampling {n} queries from {input_file}...")
    with open(input_file, 'r') as f:
        lines = [line.strip() for line in f if line.strip()]
    
    random.seed(seed)
    if len(lines) > n:
        sampled_lines = random.sample(lines, n)
    else:
        sampled_lines = lines
        
    with open(output_file, 'w') as f:
        for line in sampled_lines:
            f.write(line + "\n")
    print(f"Saved {len(sampled_lines)} samples to {output_file}")
    return len(sampled_lines)

def run_evaluation(temp_input, output_csv, env_vars, workers=5):
    cmd = [
        sys.executable,
        "scripts/evaluate_recovered_samples.py",
        "--input", temp_input,
        "--output", output_csv,
        "--workers", str(workers)
        # --limit is implied by input file size
    ]
    
    print(f"\n>>> Running: {' '.join(cmd)}")
    print(f"    Env: {env_vars}")
    
    env = os.environ.copy()
    env.update(env_vars)
    
    subprocess.run(cmd, env=env, check=True)

def generate_plot(offline_csv, hybrid_csv, output_plot):
    print("\nGenerating Comparison Plot...")
    try:
        df_off = pd.read_csv(offline_csv)
        df_hyb = pd.read_csv(hybrid_csv)
        
        # Merge on chemical_name (assuming unique in this batch)
        # Or query. But chemical_name is extracted and should be stable.
        
        # Ensure 'normalized_prediction' exists
        if "normalized_prediction" not in df_off.columns:
            df_off["normalized_prediction"] = "Error"
        if "normalized_prediction" not in df_hyb.columns:
            df_hyb["normalized_prediction"] = "Error"
            
        # Clean columns
        df_off = df_off.rename(columns={"normalized_prediction": "Offline Prediction", "agent_verdict": "Offline Verdict"})
        df_hyb = df_hyb.rename(columns={"normalized_prediction": "Hybrid Prediction", "agent_verdict": "Hybrid Verdict"})
        
        merged = pd.merge(
            df_off[["chemical_name", "Offline Prediction", "Offline Verdict"]],
            df_hyb[["chemical_name", "Hybrid Prediction", "Hybrid Verdict"]],
            on="chemical_name",
            how="inner"
        )
        
        print(f"Merged {len(merged)} results.")
        
        # Calculate Agreement
        merged["Agreement"] = merged["Offline Prediction"] == merged["Hybrid Prediction"]
        agreement_rate = merged["Agreement"].mean()
        print(f"Agreement Rate: {agreement_rate:.2%}")
        
        # Plot Usage
        # Stacked Bar Chart of Outcomes
        
        # Outcomes: Yes, No, Unclear, Error (normalize strings)
        valid_outcomes = ["Yes", "No", "Unclear", "Error"]
        
        def normalize(x):
            x = str(x).strip()
            if x in valid_outcomes: return x
            if "Yes" in x: return "Yes"
            if "No" in x: return "No"
            return "Unclear"

        merged["Offline Prediction"] = merged["Offline Prediction"].apply(normalize)
        merged["Hybrid Prediction"] = merged["Hybrid Prediction"].apply(normalize)
        
        # Count outcomes
        off_counts = merged["Offline Prediction"].value_counts().reindex(valid_outcomes, fill_value=0)
        hyb_counts = merged["Hybrid Prediction"].value_counts().reindex(valid_outcomes, fill_value=0)
        
        # Plot
        fig, ax = plt.subplots(figsize=(10, 6))
        
        x = range(len(valid_outcomes))
        width = 0.35
        
        ax.bar([i - width/2 for i in x], off_counts, width, label='Offline Only')
        ax.bar([i + width/2 for i in x], hyb_counts, width, label='Hybrid')
        
        ax.set_ylabel('Count')
        ax.set_title(f'Offline vs Hybrid Verdict Distribution (N={len(merged)})')
        ax.set_xticks(x)
        ax.set_xticklabels(valid_outcomes)
        ax.legend()
        
        plt.tight_layout()
        plt.savefig(output_plot)
        print(f"Plot saved to {output_plot}")
        
        # Save merged CSV comparison
        csv_path = output_plot.replace(".png", ".csv")
        merged.to_csv(csv_path, index=False)
        print(f"Comparison Data saved to {csv_path}")
        
    except Exception as e:
        print(f"Error generating plot: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()

    input_jsonl = "agent/searching_results/e2e_run_20260125_130247/recovered_queries_full.jsonl"
    temp_jsonl = "temp_comparison_samples_50.jsonl"
    
    # Files
    offline_csv = "comparison_results_offline_50.csv"
    hybrid_csv = "comparison_results_hybrid_50.csv"
    plot_file = "comparison_offline_vs_hybrid_50.png"
    
    # 0. Sample
    if not os.path.exists(temp_jsonl):
        sample_queries(input_jsonl, temp_jsonl, n=50)
    else:
        print(f"Using existing samples file: {temp_jsonl}")
        
    # 1. Run Offline
    # Force fresh file
    if os.path.exists(offline_csv): os.remove(offline_csv)
    
    print("\n---------- STARTING OFFLINE RUN ----------")
    run_evaluation(
        temp_input=temp_jsonl, 
        output_csv=offline_csv, 
        env_vars={
            "INCLUDE_ONLINE_SEARCH": "False",
            "INCLUDE_OFFLINE_SEARCH": "True",
            "CUDA_VISIBLE_DEVICES": "1" # User Requested GPU 1
        },
        workers=args.workers
    )
    
    # 2. Run Hybrid
    if os.path.exists(hybrid_csv): os.remove(hybrid_csv)
    
    print("\n---------- STARTING HYBRID RUN ----------")
    run_evaluation(
        temp_input=temp_jsonl, 
        output_csv=hybrid_csv, 
        env_vars={
            "INCLUDE_ONLINE_SEARCH": "True",
            "INCLUDE_OFFLINE_SEARCH": "True",
            "CUDA_VISIBLE_DEVICES": "1" # User Requested GPU 1
        },
        workers=args.workers
    )
    
    # 3. Plot
    generate_plot(offline_csv, hybrid_csv, plot_file)

if __name__ == "__main__":
    main()
