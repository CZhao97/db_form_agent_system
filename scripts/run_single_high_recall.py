
import sys
# MOCK SQLITE (CRITICAL: Must be first)
from unittest.mock import MagicMock
sys.modules["sqlite3"] = MagicMock()
sys.modules["sqlite3.dbapi2"] = MagicMock()

import logging
import time
import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

# Run in agent directory
# This ensures that when we import notebooks.e2e_agent, it finds 'notebooks' package
# AND inside e2e_agent, it appends '../code' relative to itself.
current_dir = os.path.dirname(os.path.abspath(__file__))
agent_root = os.path.join(current_dir, "../")
os.chdir(agent_root)
sys.path.append(agent_root)
# Also add 'notebooks' to path so 'ner_results_viewer' imports work inside e2e_agent
sys.path.append(os.path.join(agent_root, "notebooks"))

# dynamic settings
os.environ["TARGET_PAPERS"] = "6000"
os.environ["SEARCH_LIMIT"] = "6000"

from notebooks.e2e_agent import upper_stream_agent_executor

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

def main():
    logger.info("Starting Single High-Recall Run...")
    
    # We use a unique thread_id to ensure a fresh state
    thread_id = f"single_run_{int(time.time())}"
    config = {"configurable": {"thread_id": thread_id}}
    
    # The prompt already contains the detailed instructions.
    # We just need to trigger it with the initial broad query.
    # The agent's internal loop (driven by the LLM deciding to call tools again) 
    # will handle the iteration.
    
    initial_message = (
        "Start the iterative literature harvesting for 'water disinfection byproducts'. "
        "Follow the high-volume iterative workflow to maximize recall."
    )
    
    state = {
        "messages": [HumanMessage(content=initial_message)]
    }
    
    try:
        # Increase recursion limit to allow for many autonomous steps
        # The prompt asks for potentially 2000-6000 papers, which might take many steps.
        # LangGraph default is usually 25. We set it higher.
        
        # Note: upper_stream_agent_executor is compiled graph. 
        # We need to pass recursion_limit in config.
        config["recursion_limit"] = 150 
        
        logger.info(f"Invoking Agent with recursion_limit=150...")
        result = upper_stream_agent_executor.invoke(state, config=config)
        
        logger.info("Run Finished Successfully.")
        
        # extract output
        last_msg = result['messages'][-1].content
        logger.info(f"Final Output:\n{last_msg}")
        
    except Exception as e:
        logger.error(f"Run Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
