import pandas as pd
import os

def analyze_progress():
    print("--- DE NOVO EXPERIMENT ---")
    dn_path = "agent/searching_results/de_novo_experiment/de_novo_results.csv"
    if os.path.exists(dn_path):
        df_dn = pd.read_csv(dn_path)
        print(f"Total Processed: {len(df_dn)}")
        confirmed = df_dn[df_dn["Prediction"] == "Confirmed"]
        print(f"Confirmed DBPs: {len(confirmed)}")
        if len(df_dn) > 0:
            print(f"Hit Rate: {len(confirmed)/len(df_dn)*100:.1f}%")
        print("\nSample Confirmed Compounds:")
        print(confirmed["Compound"].head(10).tolist())
    else:
        print("No results file found.")

    print("\n--- ABLATION STUDY ---")
    ab_path = "agent/searching_results/ablation_study/ablation_results_FULL_RESUME.csv"
    if os.path.exists(ab_path):
        df_ab = pd.read_csv(ab_path)
        print(f"Total Processed: {len(df_ab)}")
        
        # Condition stats
        if "Condition" in df_ab.columns:
            print(df_ab.groupby("Condition").size())
            
        # Accuracy
        if "IsCorrect" in df_ab.columns:
            acc = df_ab["IsCorrect"].mean()
            print(f"Overall Accuracy: {acc*100:.1f}%")
            
            # Precision/Recall per condition
            for name, group in df_ab.groupby("Condition"):
                 acc_grp = group["IsCorrect"].mean()
                 print(f"  {name}: {acc_grp*100:.1f}%")
    else:
        print("No results file found.")

if __name__ == "__main__":
    analyze_progress()
