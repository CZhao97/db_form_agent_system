import pandas as pd
import time
import os
from pathlib import Path

MAIN_CSV = 'manuscript/data/comparison_results_offline_vs_hybrid.csv'
RERUN_CSV = 'offline_rerun.csv'
LOG_FILE = 'offline_benchmark.log'

print('Watching for offline MAS benchmark to complete...')

while True:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            content = f.read()
            if 'Done.' in content:
                print('Benchmark completed!')
                break
    time.sleep(30)

print(f'Loading {RERUN_CSV} to merge offline columns...')
# The rerun script generates 'offline_rerun.csv'.
# We extract 'IUPAC name', 'offline_cost_usd', 'offline_tokens_used', 'offline_papers_analyzed'
df_rerun = pd.read_csv(RERUN_CSV)

df_main = pd.read_csv(MAIN_CSV)

# Update main dataframe with the new offline columns
for idx, row in df_rerun.iterrows():
    compound = row['IUPAC name']
    mask = df_main['IUPAC name'] == compound
    if mask.any():
        df_main.loc[mask, 'offline_cost_usd'] = row.get('offline_cost_usd', 0.0)
        df_main.loc[mask, 'offline_tokens_used'] = row.get('offline_tokens_used', 0)
        df_main.loc[mask, 'offline_papers_analyzed'] = row.get('offline_papers_analyzed', 0)
        df_main.loc[mask, 'offline_relevant_chunks'] = row.get('offline_relevant_chunks', 0)

# Save merged back
df_main.to_csv(MAIN_CSV, index=False)
print(f'Successfully updated {MAIN_CSV} with real offline MAS tracking data!')

# Trigger figure regeneration
print('Triggering figure update...')
os.system('MPLBACKEND=Agg .venv312/bin/python notebooks/generate_mas_vs_paperqa_figure.py')
print('Figure regeneration done!')
