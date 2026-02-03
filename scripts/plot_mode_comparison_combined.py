import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# Load Data
CSV_PATH = "comparison_results_offline_vs_hybrid.csv"
OUTPUT_PLOT = "comparison_combined_plot.png"

def normalize_verdict(v):
    v = str(v).lower()
    if 'not confirmed' in v:
        return 'Not Confirmed / Unclear'
    if 'confirmed' in v:
        return 'Confirmed'
    if 'suspected' in v:
        return 'Suspected'
    if 'unclear' in v:
        return 'Not Confirmed / Unclear'
    if 'error' in v:
        return 'Error'
    return 'Other'

def main():
    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        print(f"Error reading {CSV_PATH}: {e}")
        return

    # Normalize Verdicts
    df['offline_clean'] = df['offline_agent_verdict'].apply(normalize_verdict)
    df['hybrid_clean'] = df['hybrid_agent_verdict'].apply(normalize_verdict)
    
    # Prepare Data for Plot 1 (Verdicts)
    
    metrics = ['Confirmed', 'Suspected', 'Not Confirmed / Unclear', 'Error']
    
    counts_offline = df['offline_clean'].value_counts()
    counts_hybrid = df['hybrid_clean'].value_counts()
    
    # Ensure all keys exist
    for m in metrics:
        if m not in counts_offline: counts_offline[m] = 0
        if m not in counts_hybrid: counts_hybrid[m] = 0
        
    # Dynamically filter out metrics with 0 count in both
    active_metrics = []
    for m in metrics:
        if counts_offline[m] > 0 or counts_hybrid[m] > 0:
            active_metrics.append(m)
    metrics = active_metrics
        
    # Vectors
    off_vec = [counts_offline[m] for m in metrics]
    hyb_vec = [counts_hybrid[m] for m in metrics]
    
    # ---------------------------------------------------------
    # Combined Figure
    # ---------------------------------------------------------
    # Set style
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams['font.family'] = 'sans-serif'
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    
    # Colors
    color_offline = "#4c72b0" # Muted Blue
    color_hybrid = "#dd8452"  # Muted Orange
    
    # --- Plot 1: Verdict Counts ---
    x = np.arange(len(metrics))
    width = 0.35
    
    rects1 = ax1.bar(x - width/2, off_vec, width, label='Offline Only', color=color_offline, alpha=0.9, edgecolor='white')
    rects2 = ax1.bar(x + width/2, hyb_vec, width, label='Hybrid', color=color_hybrid, alpha=0.9, edgecolor='white')
    
    ax1.set_ylabel('Number of Compounds', fontsize=14, fontweight='bold')
    ax1.set_title('Distribution by Mode', fontsize=16, fontweight='bold', pad=20)
    ax1.set_xticks(x)
    ax1.set_xticklabels(metrics, fontsize=12)
    ax1.legend(frameon=True, fancybox=True, framealpha=0.9)
    ax1.bar_label(rects1, padding=3, fontsize=12, fontweight='bold')
    ax1.bar_label(rects2, padding=3, fontsize=12, fontweight='bold')
    ax1.grid(axis='y', linestyle='--', alpha=0.6)
    ax1.xaxis.grid(False) # Explicitly disable vertical grid lines
    sns.despine(ax=ax1, left=True) # Remove left spine, keep grid

    # --- Plot 2: Efficiency ---
    # Clean durations
    df['offline_duration_seconds'] = pd.to_numeric(df['offline_duration_seconds'], errors='coerce').fillna(0)
    df['hybrid_duration_seconds'] = pd.to_numeric(df['hybrid_duration_seconds'], errors='coerce').fillna(0)
    
    avg_durations = [df['offline_duration_seconds'].mean(), df['hybrid_duration_seconds'].mean()]
    labels_eff = ['Offline Only', 'Hybrid']
    colors_eff = [color_offline, color_hybrid]
    
    bars = ax2.bar(labels_eff, avg_durations, color=colors_eff, width=0.5, alpha=0.9, edgecolor='white')
    
    ax2.set_ylabel('Average Duration (seconds)', fontsize=14, fontweight='bold')
    ax2.set_title('Runtime Efficiency Comparison', fontsize=16, fontweight='bold', pad=20)
    ax2.grid(axis='y', linestyle='--', alpha=0.6)
    ax2.xaxis.grid(False)
    sns.despine(ax=ax2, left=True)
    
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + (height*0.02),
                 f'{height:.1f}s',
                 ha='center', va='bottom', fontsize=14, fontweight='bold', color='black')
         
    # Adjust layout
    plt.tight_layout()
    
    # Add a suptitle?
    # fig.suptitle('Offline vs Hybrid Mode Evaluation (N=50)', fontsize=20, fontweight='bold', y=1.05)
    
    plt.savefig(OUTPUT_PLOT, dpi=300, bbox_inches='tight')
    print(f"Saved {OUTPUT_PLOT}")

if __name__ == "__main__":
    main()
