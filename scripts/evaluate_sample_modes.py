
import os
import sys
import subprocess
import pandas as pd
import random
import time

# Compounds to test (3 confirmed DBPs, 2 negative/unknown)
# Using known compounds for meaningful comparison
TEST_COMPOUNDS = [
    "4-Bromophenol",  # We know this one has offline data
    "3-Chloro-4-(dichloromethyl)-2-furanone", # MX
    "Chloroform",
    "Acetylsalicylic acid", # Likely negative
    "Caffeine" # Likely negative
]

SCRIPT_PATH = "notebooks/evaluate_dbp_downstream_only.py"

def run_evaluation(mode_name, env_vars, compounds):
    print(f"\n{'='*60}")
    print(f"RUNNING EVALUATION MODE: {mode_name}")
    print(f"Env: {env_vars}")
    print(f"{'='*60}\n")
    
    # Create a temporary input file with just these compounds
    temp_input_csv = f"temp_input_{mode_name}.csv"
    pd.DataFrame({"Compound Name": compounds, "GroundTruth": ["Unknown"]*len(compounds)}).to_csv(temp_input_csv, index=False)

    # We need to run the script. It normally reads "evaluation_results_new.csv".
    # We might need to modify the script to read our temp file OR just call the function directly if we write a python wrapper.
    # Calling subprocess is cleaner for env var isolation but we need to control input.
    # Actually, evaluate_dbp_downstream_only.py generally iterates over a loaded DB.
    # Let's write a python wrapper that imports the function instead of subprocess, 
    # BUT we need to reload modules to change env vars effectively if e2e_agent is imported at top level.
    # Subprocess is safer for env vars.
    
    # Limitation: evaluate_dbp_downstream_only.py loads specific filenames.
    # Let's bypass the script and use a direct python driver here that imports e2e_agent
    pass

def main():
    # Because e2e_agent.py reads os.environ at IMPORT time (in the global scope tool init),
    # we CANNOT easily toggle it within one python process by just changing os.environ.
    # We must use subprocess logic.
    
    # Strategy: 
    # 1. Create a "driver_subprocess.py" that imports e2e_agent and runs specific compounds.
    # 2. Call it twice with different env vars.
    
    driver_code = """
import sys
import os
import pandas as pd
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'notebooks'))

# Set args for e2e_agent (must happen before import if it reads env)
# Actually we set env in subprocess call.

from notebooks.evaluate_dbp_downstream_only import evaluate_compound

compounds = [
    "4-Bromophenol",
    "Chloroform",
    "Caffeine"
]

results = []
for c in compounds:
    print(f"Processing {c}...")
    res = evaluate_compound(c)
    results.append(res)
    print(f"Result for {c}: {res['agent_verdict']}")

df = pd.DataFrame(results)
print(df[['input_compound', 'agent_verdict', 'session_dir']])
"""
    
    with open("temp_driver.py", "w") as f:
        f.write(driver_code)
        
    modes = [
        ("ONLINE_ONLY", {"INCLUDE_ONLINE_SEARCH": "True", "INCLUDE_OFFLINE_SEARCH": "False"}),
        ("OFFLINE_ONLY", {"INCLUDE_ONLINE_SEARCH": "False", "INCLUDE_OFFLINE_SEARCH": "True"})
    ]
    
    for name, env in modes:
        print(f"\n>>> STARTING {name} <<<")
        # Copy current env and update
        current_env = os.environ.copy()
        current_env.update(env)
        
        try:
            subprocess.run([sys.executable, "temp_driver.py"], env=current_env, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error running {name}: {e}")
            
    # Cleanup
    if os.path.exists("temp_driver.py"):
        os.remove("temp_driver.py")

if __name__ == "__main__":
    main()
