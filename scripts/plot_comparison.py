import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

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

    # Merge
    print("Merging on 'IUPAC name'...")
    # Ensure column names match exactly
    if 'IUPAC name' not in df_agent.columns or 'IUPAC name' not in df_base.columns:
        print("Error: 'IUPAC name' column missing in one of the files.")
        return
        
    merged = pd.merge(df_agent, df_base, on="IUPAC name", how="inner", suffixes=('_agent', '_base'))
    print(f"Matched {len(merged)} compounds.")
    
    # Analyze values
    def normalize(val):
        s = str(val).lower()
        if "confirmed" in s and "not" not in s: return "Confirmed"
        if "confirmed" in s and "not" in s: return "Not Confirmed"
        if "suspected" in s: return "Suspected"
        if "unclear" in s: return "Unclear"
        return "Not Confirmed" # Default fallback
    
    merged['Agent Category'] = merged['normalized_prediction'].apply(normalize)
    merged['Baseline Category'] = merged['Model Prediction'].apply(normalize)
    
    # Save merged data
    merged_output = "comparison_merged.csv"
    merged.to_csv(merged_output, index=False)
    print(f"Saved merged data to {merged_output}")
    
    # Plotting
    # Count stats
    cats = ['Confirmed', 'Suspected', 'Unclear', 'Not Confirmed']
    agent_counts = merged['Agent Category'].value_counts().reindex(cats, fill_value=0)
    base_counts = merged['Baseline Category'].value_counts().reindex(cats, fill_value=0)
    
    plot_data = pd.DataFrame({
        'Verdict': cats,
        'Agent (Literature)': agent_counts.values,
        'Baseline (Gemini Flash 2.5)': base_counts.values
    })
    
    df_melted = plot_data.melt(id_vars='Verdict', var_name='System', value_name='Count')
    
    plt.figure(figsize=(10, 6))
    sns.set_theme(style="whitegrid")
    
    ax = sns.barplot(
        data=df_melted,
        x='Verdict',
        y='Count',
        hue='System',
        palette=['#2ecc71', '#95a5a6'] 
    )
    
    for container in ax.containers:
        ax.bar_label(container)
        
    plt.title(f'Agent vs Baseline Performance (N={len(merged)} Compounds)', fontsize=14, fontweight='bold')
    plt.xlabel('Final Verdict', fontsize=12)
    plt.ylabel('Number of Compounds', fontsize=12)
    plt.legend(title='System')
    
    output_img = "comparison_bar_chart.png"
    plt.savefig(output_img, dpi=300, bbox_inches='tight')
    print(f"Chart saved to {output_img}")

if __name__ == "__main__":
    main()
