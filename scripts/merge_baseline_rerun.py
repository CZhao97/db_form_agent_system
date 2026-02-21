import pandas as pd

# Load previous comparison
df_final = pd.read_csv("final_ablation_comparison.csv")
print(f"Original shape: {df_final.shape}")

# Load BASELINE rerun results
rerun_path = "agent/searching_results/ablation_study/Baseline_Rerun.csv"
try:
    df_rerun = pd.read_csv(rerun_path)
    print(f"Baseline Rerun shape: {df_rerun.shape}")
except FileNotFoundError:
    print("Baseline Rerun file not found yet!")
    exit(1)

# Create a mapping dictionary from rerun
rerun_map = {}
for _, row in df_rerun.iterrows():
    compound = row['IUPAC name']
    verdict = row['normalized_prediction']
    rerun_map[compound] = verdict

# Function to update verdict
def update_verdict(row):
    cmp = row['Compound']
    old_verdict = row['Baseline_Verdict']
    
    # If old verdict is error, check rerun
    if "Error" in str(old_verdict):
        if cmp in rerun_map:
            return rerun_map[cmp]
    return old_verdict

# Apply update
df_final['Baseline_Verdict'] = df_final.apply(update_verdict, axis=1)

# Re-calculate Score based on Updated Verdict
def normalize_verdict(label):
    if pd.isna(label): return 0
    s = str(label).lower().strip()
    if "not confirmed" in s: return 0
    if "confirmed" in s: return 1
    if "true" in s: return 1
    return 0

df_final['Baseline_Score'] = df_final['Baseline_Verdict'].apply(normalize_verdict)

# Check how many errors remain
errors_left = df_final[df_final['Baseline_Verdict'].astype(str).str.contains("Error", case=False, na=False)]
print(f"Baseline Errors remaining: {len(errors_left)}")

# Save
df_final.to_csv("final_ablation_comparison.csv", index=False)
print("Updated final_ablation_comparison.csv with BASELINE rerun results.")

# Print new stats
print(df_final['Baseline_Verdict'].value_counts())
print(f"New Baseline Recall (Strict): {df_final['Baseline_Score'].mean():.2%}")
