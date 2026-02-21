import pandas as pd

# Load previous comparison
df_final = pd.read_csv("final_ablation_comparison.csv")
print(f"Original shape: {df_final.shape}")

# Load rerun results
df_rerun = pd.read_csv("agent/searching_results/ablation_study/No_Critique_Rerun.csv")
print(f"Rerun shape: {df_rerun.shape}")
# Ensure column names align. Rerun has 'IUPAC name', 'agent_verdict', 'normalized_prediction'
# Or from evaluate_dbp_downstream_only it returns specific columns. Let's check.
# The script evaluate_dbp_downstream_only writes columns: IUPAC name, agent_verdict, normalized_prediction.

# We need to map rerun to final format:
# Compound, Ablation_Verdict, Ablation_Score (recalc)

# Create a mapping dictionary from rerun
rerun_map = {}
for _, row in df_rerun.iterrows():
    compound = row['IUPAC name']
    verdict = row['normalized_prediction'] # Use normalized prediction as verdict?
    # Or agent_verdict? Usually normalized_prediction is better (e.g. extracts from JSON).
    rerun_map[compound] = verdict

# Function to update verdict
def update_verdict(row):
    cmp = row['Compound']
    old_verdict = row['Ablation_Verdict']
    
    # If old verdict is error, check rerun
    if "Error" in str(old_verdict):
        if cmp in rerun_map:
            return rerun_map[cmp]
    return old_verdict

# Apply update
df_final['Ablation_Verdict'] = df_final.apply(update_verdict, axis=1)

# Re-calculate Score based on Updated Verdict
def normalize_verdict(label):
    if pd.isna(label): return 0
    s = str(label).lower().strip()
    if "not confirmed" in s: return 0
    if "confirmed" in s: return 1
    if "true" in s: return 1 # Fallback for some boolean strings
    return 0

df_final['Ablation_Score'] = df_final['Ablation_Verdict'].apply(normalize_verdict)

# Check how many errors remain
errors_left = df_final[df_final['Ablation_Verdict'].astype(str).str.contains("Error", case=False, na=False)]
print(f"Errors remaining: {len(errors_left)}")

# Save
df_final.to_csv("final_ablation_comparison.csv", index=False)
print("Updated final_ablation_comparison.csv with rerun results.")

# Print new stats
print(df_final['Ablation_Verdict'].value_counts())
print(f"New Recall (Strict): {df_final['Ablation_Score'].mean():.2%}")
