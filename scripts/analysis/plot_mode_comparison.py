import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# Load Data
CSV_PATH = "comparison_results_offline_vs_hybrid.csv"
OUTPUT_QUALITY = "comparison_quality_plot.png"
OUTPUT_EFFICIENCY = "comparison_efficiency_plot.png"

def main():
    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        print(f"Error reading {CSV_PATH}: {e}")
        return

    # Clean numeric columns
    numeric_cols = [
        'offline_papers_analyzed', 'hybrid_papers_analyzed',
        'offline_relevant_chunks', 'hybrid_relevant_chunks',
        'offline_duration_seconds', 'hybrid_duration_seconds'
    ]
    
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # ---------------------------------------------------------
    # Figure X: Quality / Coverage (Papers & Relevant Chunks)
    # ---------------------------------------------------------
    plt.figure(figsize=(10, 6))
    
    # Calculate means
    means_quality = df[[
        'offline_papers_analyzed', 'hybrid_papers_analyzed',
        'offline_relevant_chunks', 'hybrid_relevant_chunks'
    ]].mean()
    
    # Prepare data for plotting
    labels = ['Papers Analyzed', 'Relevant Chunks']
    offline_vals = [means_quality['offline_papers_analyzed'], means_quality['offline_relevant_chunks']]
    hybrid_vals = [means_quality['hybrid_papers_analyzed'], means_quality['hybrid_relevant_chunks']]
    
    x = np.arange(len(labels))
    width = 0.35
    
    fig, ax = plt.subplots(figsize=(8, 6))
    rects1 = ax.bar(x - width/2, offline_vals, width, label='Offline Only', color='skyblue')
    rects2 = ax.bar(x + width/2, hybrid_vals, width, label='Hybrid', color='salmon')
    
    ax.set_ylabel('Count (Average per Compound)')
    ax.set_title('Figure X: Impact of Retrieval Mode on Coverage')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    
    # Add counts
    ax.bar_label(rects1, padding=3, fmt='%.1f')
    ax.bar_label(rects2, padding=3, fmt='%.1f')
    
    plt.tight_layout()
    plt.savefig(OUTPUT_QUALITY, dpi=300)
    print(f"Saved {OUTPUT_QUALITY}")
    plt.close()

    # ---------------------------------------------------------
    # Figure Y: Efficiency (Runtime)
    # ---------------------------------------------------------
    plt.figure(figsize=(8, 6))
    
    # Calculate mean durations
    avg_durations = [df['offline_duration_seconds'].mean(), df['hybrid_duration_seconds'].mean()]
    labels_eff = ['Offline Only', 'Hybrid']
    colors_eff = ['skyblue', 'salmon']
    
    bars = plt.bar(labels_eff, avg_durations, color=colors_eff, width=0.6)
    
    plt.ylabel('Average Duration (seconds)')
    plt.title('Figure Y: Runtime Efficiency Comparison')
    
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height,
                 f'{height:.1f}s',
                 ha='center', va='bottom')
    
    plt.tight_layout()
    plt.savefig(OUTPUT_EFFICIENCY, dpi=300)
    print(f"Saved {OUTPUT_EFFICIENCY}")
    plt.close()

if __name__ == "__main__":
    main()
