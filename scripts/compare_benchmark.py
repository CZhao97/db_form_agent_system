
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix, classification_report

def normalize_verdict(v):
    if not isinstance(v, str):
        return "Unclear"
    v = v.lower().strip()
    if "not confirmed" in v or "not_confirmed" in v or "non-dbp" in v:
        return "Not Confirmed"
    if "confirmed" in v:
        return "Confirmed DBP"
    if "suspected" in v:
        # Treat suspected as Confirmed for binary comparison, or separate?
        # User usually cares about detection. Let's keep it separate for now.
        return "Suspected DBP"
    return "Unclear"

try:
    # Load Agent Results
    df_agent = pd.read_csv("evaluation_results_full_fresh_k10.csv")
    df_agent['Agent_Verdict'] = df_agent['normalized_prediction'].apply(normalize_verdict)
    
    # Load Baseline (Gemini Flash)
    df_base = pd.read_excel("notebooks/dbp_gemini_flash_2_5_results.xlsx")
    # Assuming baseline has 'IUPAC name' and 'Verdict' or similar. 
    # Let's check columns first, but writing generic logic.
    if 'Model Prediction' in df_base.columns:
        # Check values. If 0/1 or similar.
        df_base['Base_Verdict'] = df_base['Model Prediction'].apply(lambda x: "Confirmed DBP" if str(x).lower() in ["1", "true", "yes", "confirmed"] else "Not Confirmed")
    elif 'verdict' in df_base.columns:
        df_base['Base_Verdict'] = df_base['verdict'].apply(normalize_verdict)
    elif 'agent_verdict' in df_base.columns:
        df_base['Base_Verdict'] = df_base['agent_verdict'].apply(normalize_verdict)
    
    # Merge
    merged = pd.merge(df_agent, df_base, on="IUPAC name", suffixes=('_Agent', '_Base'), how='inner')
    
    print(f"Total Overlap: {len(merged)}")
    
    # Comparison Matrix
    print("\n--- Confusion Matrix (Agent vs Baseline) ---")
    print(pd.crosstab(merged['Agent_Verdict'], merged['Base_Verdict']))
    
    # Discrepancies
    discrepancies = merged[merged['Agent_Verdict'] != merged['Base_Verdict']]
    print(f"\nTotal Discrepancies: {len(discrepancies)}")
    
    # Save detailed comparison
    merged.to_csv("comparison_agent_vs_gemini_flash.csv", index=False)
    print("\nDetailed comparison saved to comparison_agent_vs_gemini_flash.csv")

except Exception as e:
    print(f"Error: {e}")
