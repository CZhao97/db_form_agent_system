import pandas as pd
import os
import glob

MAIN_CSV = "comparison_results_offline_vs_hybrid.csv"

def main():
    print(f"Loading main CSV: {MAIN_CSV}")
    df_main = pd.read_csv(MAIN_CSV)
    
    # Find shard files
    shard_files = glob.glob("comparison_results_offline_shard_*.csv")
    print(f"Found {len(shard_files)} shard files: {shard_files}")
    
    total_updated = 0
    
    for sfile in shard_files:
        print(f"Processing {sfile}...")
        try:
            df_shard = pd.read_csv(sfile)
            
            # Update main dataframe
            # We assume the index in shard files corresponds to the original dataframe index
            # because we used df.loc[indices] and kept index in to_csv
            
            # However, read_csv might treat index as a column unless specified.
            # Let's check columns.
            if "Unnamed: 0" in df_shard.columns:
                 df_shard = df_shard.set_index("Unnamed: 0")
            
            # Use combine_first or manual update?
            # df_main.update(df_shard) updates in place using index alignment.
            # This is exactly what we want.
            
            # But we only want to update columns that are present in shard (offline_*)
            # And only if they are not NaN (though main has NaN, shard should have values)
            
            count_before = df_main['offline_agent_verdict'].notna().sum()
            df_main.update(df_shard)
            count_after = df_main['offline_agent_verdict'].notna().sum()
            
            print(f"  -> Updated main DF. Valid Offline Verdicts: {count_before} -> {count_after}")
            total_updated += (count_after - count_before)
            
        except Exception as e:
            print(f"  -> Error merging {sfile}: {e}")
            
    print(f"Saving merged CSV to {MAIN_CSV}")
    df_main.to_csv(MAIN_CSV, index=False)
    print("Done.")

if __name__ == "__main__":
    main()
