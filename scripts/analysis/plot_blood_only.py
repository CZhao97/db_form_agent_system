
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

# Load Data
if not os.path.exists("blood_eval_pure_llm.csv"):
    print("Error: blood_eval_pure_llm.csv not found. Run run_pure_llm_blood.py first.")
    exit(1)

df_agent = pd.read_csv("evaluation_results_blood.csv")
df_llm = pd.read_csv("blood_eval_pure_llm.csv")

# Rename Agent Verdict
df_agent = df_agent.rename(columns={'input_compound': 'Compound', 'agent_verdict': 'Agent_Verdict'})
df_agent = df_agent.drop_duplicates(subset=['Compound'])

# Merge
df_merged = pd.merge(df_agent, df_llm, on='Compound', how='inner')

# Normalize
# Merge 'Unclear' into 'Not Confirmed'
def normalize(v):
    v = str(v).lower()
    if 'yes' in v or 'confirmed' in v: return 'Confirmed'
    return 'Not Confirmed' 

df_merged['Pure_LLM_Norm'] = df_merged['Pure_LLM_Verdict'].apply(normalize)
df_merged['Agent_Norm'] = df_merged['Agent_Verdict'].apply(lambda x: 'Confirmed' if 'Confirmed' in str(x) else 'Not Confirmed')

# Plotting
sns.set_theme(style="white", rc={"axes.grid": True, "grid.color": ".9", "axes.spines.right": False, "axes.spines.top": False, "axes.spines.left": False})
plt.figure(figsize=(8, 6))

# Prepare Data for Plot
plot_data = []
order = ["Confirmed", "Not Confirmed"]

# Legend Names
legend_map = {
    "Agent_Norm": "MAS (gemini 2.5 flash)",
    "Pure_LLM_Norm": "baseline (gemini 2.5 flash)"
}

for col, method_name in legend_map.items():
    counts = df_merged[col].value_counts().reindex(order, fill_value=0)
    for label, count in counts.items():
        plot_data.append({
            "Verdict": label,
            "Method": method_name,
            "Count": int(count)
        })

plot_df = pd.DataFrame(plot_data)

# Palette
custom_palette = {
    "MAS (gemini 2.5 flash)": "#4c72b0",      # Blue
    "baseline (gemini 2.5 flash)": "#55a868"  # Green
}

ax = sns.barplot(
    data=plot_df,
    x="Verdict",
    y="Count",
    hue="Method",
    palette=custom_palette,
    saturation=0.9,
    edgecolor="white",
    linewidth=1
)

plt.title("Blood Exposome Verification: MAS vs Baseline\n(N={} Compounds)".format(len(df_merged)), fontsize=16, fontweight='bold', pad=20, color="#333333")
plt.xlabel("", fontsize=12)
plt.ylabel("Number of Compounds", fontsize=12, color="#555555")
plt.legend(title="", frameon=False)

# Annotations
for p in ax.patches:
    height = p.get_height()
    if height > 0:
        ax.text(
            p.get_x() + p.get_width() / 2., 
            height + 2, 
            str(int(height)), 
            ha="center", 
            fontsize=11, 
            fontweight='bold', 
            color='#333333'
        )

plt.tight_layout()
plt.savefig("blood_agent_vs_llm.png", dpi=300, bbox_inches='tight')
print("Saved comparison plot to blood_agent_vs_llm.png")
