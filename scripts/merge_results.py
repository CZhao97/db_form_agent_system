import pandas as pd
import os

# Paths
BASELINE_PATH = "evaluation_results_full_fresh_k10.csv"
ABLATION_PATH = "agent/searching_results/ablation_study/ablation_results_FULL_RESUME.csv"
OUTPUT_PATH = "final_ablation_comparison.csv"

def normalize_verdict(v):
    if pd.isna(v): return "Unknown"
    v = str(v).lower()
    if "confirmed" in v and "not" not in v: return 1
    if "true" == v: return 1
    if "not confirmed" in v: return 0
    if "false" == v: return 0
    if "suspected" in v: return 0.5
    if "unclear" in v: return 0.5
    return 0 

# Load Data
print(f"Loading Baseline: {BASELINE_PATH}")
df_base = pd.read_csv(BASELINE_PATH)
df_base = df_base.rename(columns={"IUPAC name": "Compound", "agent_verdict": "Baseline_Verdict"})

print(f"Loading Ablation: {ABLATION_PATH}")
df_sem = pd.read_csv(ABLATION_PATH)
# Ablation columns: Condition,Compound,GroundTruth,Verdict,IsPositive,IsCorrect

# Merge
# We want to compare Baseline Verdict vs Ablation Verdict
# Baseline: 'normalized_prediction' is the cleaned column? 
# Let's check Baseline columns
if 'normalized_prediction' in df_base.columns:
    df_base['Baseline_Score'] = df_base['normalized_prediction'].apply(normalize_verdict)
else:
    df_base['Baseline_Score'] = df_base['Baseline_Verdict'].apply(normalize_verdict)

# Ablation columns: Condition,Compound,GroundTruth,Verdict,IsPositive
# Note: IsPositive in source might be flawed (naive substring check). Re-calculate from Verdict.
df_sem = df_sem[['Compound', 'Verdict', 'GroundTruth']].rename(columns={'Verdict': 'Ablation_Verdict'})
df_sem['Ablation_Score'] = df_sem['Ablation_Verdict'].apply(normalize_verdict)


# Inner Join to keep only intersection (684 common)
merged = pd.merge(df_base, df_sem, on="Compound", how="inner")

print(f"Merged Shape: {merged.shape}")
print("Baseline NaNs:", merged['Baseline_Verdict'].isna().sum())
print("Ablation NaNs:", merged['Ablation_Verdict'].isna().sum())

# Save
merged.to_csv(OUTPUT_PATH, index=False)
print(f"Saved merged results to {OUTPUT_PATH}")
