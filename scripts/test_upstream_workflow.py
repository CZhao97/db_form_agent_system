
"""
Script to test the Upstream Agent workflow (Iterative Search -> NER).
This version is cleaned up to remove strict PubMed filters.

Usage:
    nohup python -u scripts/test_upstream_workflow.py > test_upstream.log 2>&1 &
"""
import sys
import os
import logging
from dotenv import load_dotenv

# Add notebooks/ and code/ to path
sys.path.append(os.path.join(os.getcwd(), 'notebooks'))
sys.path.append(os.path.join(os.getcwd(), 'code'))

# Setup Environment
load_dotenv()
# Ensure offline search is enabled for the test
os.environ["INCLUDE_OFFLINE_SEARCH"] = "True"
os.environ["INCLUDE_S2"] = "True"

# LangSmith Settings
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "Agent Verify Upstream (Full)"

# MOCK SQLITE to bypass broken env
import sys
from unittest.mock import MagicMock
sys.modules["sqlite3"] = MagicMock()
sys.modules["sqlite3.dbapi2"] = MagicMock()

from langchain_core.messages import HumanMessage
from e2e_agent import upper_stream_agent_executor, UpperAgentState

def test_upstream_workflow():
    print("--- Testing Upstream Agent Workflow (Iterative + Inspection) ---")
    
    query = "Identify novel disinfection byproducts formed by chlorination of drinking water with bromide."
    print(f"Query: {query}")
    
    # Mock Initial State
    state = {
        "messages": [HumanMessage(content=query)],
        "original_query": query,
        "search_session_dir": "/home/chen/GNPS_SIM/agent/db_form_agent_system/searching_results/test_upstream_workflow",
        "iteration_count": 0,
        "last_output": None
    }
    
    # Create session dir
    import shutil
    if os.path.exists(state["search_session_dir"]):
        shutil.rmtree(state["search_session_dir"])
    os.makedirs(state["search_session_dir"], exist_ok=True)
    
    print(f"Session Dir: {state['search_session_dir']}")
    
    try:
        # Invoke Agent
        # We need to pass the configurable session_dir as done in upper_stream_agent_node
        # ADDED thread_id for checkpointer
        config = {"configurable": {"search_session_dir": state["search_session_dir"], "thread_id": "test_thread_1"}}
        
        print("Invoking Agent... (This may take a minute)")
        result = upper_stream_agent_executor.invoke(state, config=config)
        
        print("\n--- Agent Execution Finished ---")
        messages = result["messages"]
        
        # ANALYSIS
        tool_calls = []
        for m in messages:
            if hasattr(m, 'tool_calls') and m.tool_calls:
                for tc in m.tool_calls:
                    tool_calls.append(tc['name'])
                    print(f"Tool Call: {tc['name']}")
                    if tc['name'] == 'fulltext_journal_search':
                        print(f"  Args: {tc['args'].get('query', 'N/A')[:100]}...")
        
        # Verify Critical Workflow Steps
        has_search = 'fulltext_journal_search' in tool_calls
        has_inspection = 'inspect_search_results' in tool_calls
        has_ner = 'chemical_ner' in tool_calls
        
        print("\n--- Verification Results ---")
        print(f"1. Called Search Tool: {'✅' if has_search else '❌'}")
        print(f"2. Called Inspection Tool: {'✅' if has_inspection else '❌ (CRITICAL FAILURE)'}")
        print(f"3. Called NER Tool: {'✅' if has_ner else '❌'}")
        
        if has_search and has_inspection:
            # Check order: Inspection should follow Search
            search_indices = [i for i, x in enumerate(tool_calls) if x == 'fulltext_journal_search']
            inspect_indices = [i for i, x in enumerate(tool_calls) if x == 'inspect_search_results']
            
            if inspect_indices and search_indices:
                first_search = search_indices[0]
                first_inspect = inspect_indices[0]
                if first_inspect > first_search:
                    print("4. Order Correct (Search -> Inspect): ✅")
                else:
                    print("4. Order Correct (Search -> Inspect): ❌ (Inspection called before Search?!)")
        
        last_msg = messages[-1]
        print(f"\nLast Message Content: {last_msg.content[:200]}...")
        
    except Exception as e:
        print(f"Execution Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_upstream_workflow()
