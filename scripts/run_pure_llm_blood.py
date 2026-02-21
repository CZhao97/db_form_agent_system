
import pandas as pd
import os
import time
from tqdm import tqdm
import pandas as pd
import os
import time
import json
from tqdm import tqdm
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

# Load Env
load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")

# Setup LLM (OpenRouter)
llm = ChatOpenAI(
    model="google/gemini-2.5-flash", # Matching the user's other script EXACTLY.
    openai_api_key=api_key,
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0.0
)

# Define Output Structure
class BloodVerdict(BaseModel):
    is_in_blood: str = Field(description="Yes, No, or Unsure")
    reasoning: str = Field(description="Brief reason for the verdict")

parser = JsonOutputParser(pydantic_object=BloodVerdict)

prompt = PromptTemplate(
    template="Answer the following question about a chemical compound.\n\nCompound: {compound}\nQuestion: Is this compound confirmed to be found in human blood (e.g., as an exposome chemical, metabolite, or drug)?\n\nProvide your answer as JSON with keys 'is_in_blood' (Yes/No/Unsure) and 'reasoning'.\n\n{format_instructions}",
    input_variables=["compound"],
    partial_variables={"format_instructions": parser.get_format_instructions()},
)

chain = prompt | llm | parser

# Load Data
# We use evaluation_results_blood.csv to get the Exact compounds the agent processed
df_agent = pd.read_csv("evaluation_results_blood.csv")
compounds = df_agent['input_compound'].unique().tolist()
print(f"Loaded {len(compounds)} unique compounds from Agent evaluation.")

results = []

print("Starting Pure LLM Evaluation...")
for cmp in tqdm(compounds):
    try:
        res = chain.invoke({"compound": cmp})
        results.append({
            "Compound": cmp,
            "Pure_LLM_Verdict": res.get("is_in_blood", "Error"),
            "Pure_LLM_Reasoning": res.get("reasoning", "")
        })
        time.sleep(0.1) # Rate limit check
    except Exception as e:
        print(f"Error for {cmp}: {e}")
        results.append({
            "Compound": cmp,
            "Pure_LLM_Verdict": "Error",
            "Pure_LLM_Reasoning": str(e)
        })

# Save Results
df_llm = pd.DataFrame(results)
df_llm.to_csv("blood_eval_pure_llm.csv", index=False)
print("Saved LLM results to blood_eval_pure_llm.csv")

# Merge and Compare
# Fix columns for merge
df_agent_renamed = df_agent[['input_compound', 'agent_verdict']].rename(columns={'input_compound': 'Compound', 'agent_verdict': 'Agent_Verdict'})
# Drop duplicates if any (agent might have run duplicates, but unique check above handles list)
df_agent_renamed = df_agent_renamed.drop_duplicates(subset=['Compound'])

df_merged = pd.merge(df_agent_renamed, df_llm, on='Compound', how='inner')
df_merged.to_csv("blood_comparison_merged.csv", index=False)

# Normalize LLM Verdict to Agent format (Merging Unclear into Not Confirmed)
def normalize(v):
    v = str(v).lower()
    if 'yes' in v or 'confirmed' in v: return 'Confirmed'
    return 'Not Confirmed' # Merge Unclear/No into Not Confirmed

df_merged['Pure_LLM_Norm'] = df_merged['Pure_LLM_Verdict'].apply(normalize)
# Agent Normalization: If it contains Confirmed -> Confirmed, else Not Confirmed
df_merged['Agent_Norm'] = df_merged['Agent_Verdict'].apply(lambda x: 'Confirmed' if 'Confirmed' in str(x) else 'Not Confirmed')

# Plotting
import matplotlib.pyplot as plt
import seaborn as sns

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
