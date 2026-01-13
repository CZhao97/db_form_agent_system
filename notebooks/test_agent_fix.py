
import sys
import os
import shutil
from dotenv import load_dotenv
import pandas as pd

# Add code dir
sys.path.append("/home/chen/GNPS_SIM/agent/db_form_agent_system/code")

# Import the agent logic from the evaluation script
# taking care to patch or import correctly. 
# Since evaluate_dbp_downstream_only.py is a script, importing might run main.
# Better to copy the relevant setup or import safe parts.
# Actually, evaluate_dbp_downstream_only defines evaluate_compound.

# Let's import from e2e_agent directly as verify logic
from e2e_agent import down_app, determine_final_claim, FullTextJournalSearchTool
from langchain_core.messages import HumanMessage
import uuid

load_dotenv()

def run_test(compound_name):
    base_results_dir = "/data/chen/e2e_searching_results_test_fix"
    if os.path.exists(base_results_dir):
        shutil.rmtree(base_results_dir)
    os.makedirs(base_results_dir, exist_ok=True)
    
    print(f"Testing compound: {compound_name}")
    print(f"Results dir: {base_results_dir}")
    
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(base_results_dir, f"dbp_eval_{session_id}")
    os.makedirs(session_dir, exist_ok=True)
    
    # Configure Tool Session
    FullTextJournalSearchTool.set_session_dir(session_dir)
    
    query = f"According to the following definition: A disinfection byproduct (DBP) is a chemical compound that is formed incidentally by the reaction of a disinfectant with organic and inorganic matter present in water, wastewater, or other matrices. To be considered 'experimentally confirmed', there must be clear evidence from a peer-reviewed study demonstrating its formation during a disinfection process and its chemical identification. Is the compound '{compound_name}' a confirmed DBP? Answer: 'Confirmed DBP' or 'Not Confirmed DBP'"
    
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "original_query": query,
        "search_session_dir": session_dir,
        "stop_history": [],
        "consecutive_no_new_evidence": 0,
        "consecutive_tool_unavailable": 0,
        "last_researcher_json": None,
        "last_critique_json": None,
        "claim_history": [],
        "confidence_history": []
    }
    
    config = {"configurable": {"thread_id": session_id, "search_session_dir": session_dir}}
    
    print("Invoking agent...")
    final_state = down_app.invoke(initial_state, config=config)
    final_claim = determine_final_claim(final_state["messages"])
    
    print(f"Final Claim: {final_claim}")
    return final_claim

if __name__ == "__main__":
    compound = "Iodoacetic acid" 
    claim = run_test(compound)
    
    if "Confirmed" in claim and "Not" not in claim:
        print("SUCCESS: Agent confirmed the DBP.")
    elif "Confirmed DBP" in claim and "Not" not in claim:
         print("SUCCESS: Agent confirmed the DBP.")
    else:
        print(f"FAILURE: Agent returned {claim}")
