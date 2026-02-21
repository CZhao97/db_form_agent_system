import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Load Data
df = pd.read_csv("final_ablation_comparison.csv")

# Focus on Verdict columns
cols = ['Baseline_Verdict', 'Ablation_Verdict']

def normalize_label(label):
    if pd.isna(label):
        return "Unknown"
    s = str(label).lower().strip()
    
    if "not confirmed" in s:
        return "Not Confirmed"
    if "confirmed" in s:
        return "Confirmed"
    if "suspected" in s:
        return "Suspected"
    if "error" in s:
        return "Error"
    if "unclear" in s:
        return "Not Confirmed" # Merged as requested
    
    return label.title() # Fallback

# Apply normalization
for col in cols:
    df[col] = df[col].apply(normalize_label)

# Prepare data for plotting
fig, axes = plt.subplots(1, 2, figsize=(16, 8), sharey=True)

# Define custom palette
custom_palette = {
    "Confirmed": "#2ca02c",      # Green
    "Suspected": "#ff7f0e",      # Orange
    "Not Confirmed": "#7f7f7f",  # Grey
    "Error": "#d62728"           # Red
}

# Define standard order for consistency
base_order = ["Confirmed", "Suspected", "Not Confirmed"]
# Check if 'Error' exists in any column
has_error = False
for col in cols:
    if "Error" in df[col].values:
        has_error = True
        break

hue_order = base_order + ["Error"] if has_error else base_order

# Set style
sns.set_theme(style="whitegrid")

for i, col in enumerate(cols):
    ax = axes[i]
    # Get counts
    counts = df[col].value_counts().reindex(hue_order, fill_value=0)
    total = len(df)
    
    # Plot
    sns.barplot(x=counts.index, y=counts.values, ax=ax, palette=custom_palette, order=hue_order)
    
    method_name = col.replace('_Verdict', '')
    ax.set_title(f"{method_name}\n(N={total})", fontsize=14, fontweight='bold')
    ax.set_xlabel("")
    ax.set_ylabel("Count" if i==0 else "")
    ax.tick_params(axis='x', rotation=0)
    
    # Add count and percentage labels
    for j, v in enumerate(counts.values):
        pct = (v / total) * 100
        ax.text(j, v + (total*0.01), f"{v}\n({pct:.1f}%)", ha='center', fontweight='bold')

plt.tight_layout()
plt.savefig("verdict_distribution.png", dpi=300)
print("Saved plot to verdict_distribution.png")
