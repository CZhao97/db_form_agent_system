import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Load Data
df = pd.read_csv("final_ablation_comparison.csv")

# Normalization Logic
def normalize_label(label):
    if pd.isna(label): return "Unknown"
    s = str(label).lower().strip()
    if "not confirmed" in s: return "Not Confirmed"
    if "confirmed" in s: return "Confirmed"
    if "suspected" in s: return "Suspected"
    if "error" in s: return "Error"
    if "unclear" in s: return "Not Confirmed"
    return label.title()

# Apply to Verdicts
df['Base_Norm'] = df['Baseline_Verdict'].apply(normalize_label)
df['Abl_Norm'] = df['Ablation_Verdict'].apply(normalize_label)

# Prepare Data for Grouped Bar Chart
data = []
order = ["Confirmed", "Suspected", "Not Confirmed"]

# Baseline Counts
base_counts = df['Base_Norm'].value_counts().reindex(order, fill_value=0)
for label, count in base_counts.items():
    data.append({
        'Verdict': label,
        'Method': 'Baseline (With Critique)',
        'Count': int(count),
        'Percentage': count / len(df)
    })

# Ablation Counts
abl_counts = df['Abl_Norm'].value_counts().reindex(order, fill_value=0)
for label, count in abl_counts.items():
    data.append({
        'Verdict': label,
        'Method': 'Ablation (No Critique)',
        'Count': int(count),
        'Percentage': count / len(df)
    })

plot_df = pd.DataFrame(data)

# Plotting
sns.set_theme(style="white", rc={"axes.grid": True, "grid.color": ".9", "axes.spines.right": False, "axes.spines.top": False, "axes.spines.left": False})
plt.figure(figsize=(12, 7))

# Define Palette (Professional & Distinct)
custom_palette = {
    "Baseline (With Critique)": "#4c72b0",  # Muted Blue
    "Ablation (No Critique)": "#dd8452"     # Muted Orange
}

ax = sns.barplot(
    data=plot_df, 
    x='Verdict', 
    y='Count', 
    hue='Method', 
    palette=custom_palette,
    saturation=0.9,
    edgecolor="white",
    linewidth=1
)

# Typography & Layout
plt.title("Impact of Critique Agent on Verdict Distribution\n(N=684 Compounds)", fontsize=18, fontweight='bold', pad=25, color="#333333")
plt.xlabel("", fontsize=12)
plt.ylabel("Number of Compounds", fontsize=13, fontweight='medium', color="#555555")
plt.xticks(fontsize=12, fontweight='bold', color="#333333")
plt.yticks(fontsize=11, color="#555555")

# Legend with better placement
plt.legend(
    title="", 
    fontsize=12, 
    loc='upper center', 
    bbox_to_anchor=(0.5, -0.1), 
    ncol=2, 
    frameon=False,
    handletextpad=0.5
)

# Annotations (Clean & Readable)
for p in ax.patches:
    height = p.get_height()
    if height > 0:
        pct = (height / 684) * 100
        # Percentage formatting
        label_text = f"{int(height)}\n({pct:.1f}%)"
        
        ax.text(
            p.get_x() + p.get_width() / 2., 
            height + 8, 
            label_text, 
            ha="center", 
            va="bottom",
            fontsize=11, 
            fontweight='bold', 
            color='#333333'
        )

# Adjust y-limit to fit labels dynamically
max_val = plot_df['Count'].max()
plt.ylim(0, max_val * 1.15) # Ensure enough headroom (15% padding)

plt.tight_layout()
plt.savefig("ablation_comparison.png", dpi=300, bbox_inches='tight')
print("Saved grouped bar chart to ablation_comparison.png")
