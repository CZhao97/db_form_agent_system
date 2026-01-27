import pandas as pd
import sys

def main():
    agent_csv = "evaluation_results_full_fresh.csv"
    baseline_xlsx = "notebooks/dbp_gemini_flash_2_5_results.xlsx"
    
    print(f"Loading Agent Results: {agent_csv}")
    try:
        df_agent = pd.read_csv(agent_csv)
    except Exception as e:
        print(f"Error loading agent CSV: {e}")
        return

    print(f"Loading Baseline Results: {baseline_xlsx}")
    try:
        df_base = pd.read_excel(baseline_xlsx)
    except Exception as e:
        print(f"Error loading baseline XLSX: {e}")
        return

    # Normalize column names for join
    # Agent has 'IUPAC name'
    # Baseline has 'IUPAC name'
    
    # Merge
    print("Merging on 'IUPAC name'...")
    merged = pd.merge(df_agent, df_base, on="IUPAC name", how="inner", suffixes=('_agent', '_base'))
    
    print(f"Matched {len(merged)} compounds.")
    
    # success/failure analysis
    # Assuming Baseline 'Model Prediction' values are like 'Confirmed', 'Suspected', etc.
    # Agent 'normalized_prediction' values are 'Confirmed DBP', 'Suspected', 'Not Confirmed', etc.
    
    # Let's verify values
    print("\n--- Value Distribution ---")
    print("Agent Verdicts:")
    print(merged['normalized_prediction'].value_counts())
    print("\nBaseline Verdicts:")
    print(merged['Model Prediction'].value_counts())
    
    # Detailed Discrepancies
    print("\n--- Discrepancies ---")
    
    for i, row in merged.iterrows():
        agent_v = str(row['normalized_prediction']).lower()
        base_v = str(row['Model Prediction']).lower()
        
        # Simple normalization for comparison
        # e.g. "confirmed dbp" == "confirmed"
        
        agent_clean = "confirmed" if "confirmed" in agent_v and "not" not in agent_v else \
                      "not confirmed" if "not" in agent_v else \
                      "suspected" if "suspected" in agent_v else \
                      "unclear" if "unclear" in agent_v else agent_v
                      
        base_clean = "confirmed" if "confirmed" in base_v and "not" not in base_v else \
                     "not confirmed" if "not" in base_v else \
                     "suspected" if "suspected" in base_v else \
                     "unclear" if "unclear" in base_v else base_v
        
        if agent_clean != base_clean:
            print(f"\n[Diff] {row['IUPAC name']}")
            print(f"  Agent:    {row['normalized_prediction']}")
            print(f"  Baseline: {row['Model Prediction']}")
    
    # Save comparison to CSV
    output_file = "comparison_agent_vs_baseline.csv"
    print(f"\nSaving comparison to {output_file}...")
    merged.to_csv(output_file, index=False)
    print("Done.")

if __name__ == "__main__":
    main()
