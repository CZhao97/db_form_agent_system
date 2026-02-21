
import sys
import os
import json
from unittest.mock import MagicMock
import shutil

# Mock SQLITE
sys.modules["sqlite3"] = MagicMock()
sys.modules["sqlite3.dbapi2"] = MagicMock()

# Setup Path
sys.path.append(os.path.join(os.getcwd(), 'notebooks'))
sys.path.append(os.path.join(os.getcwd(), 'code'))

from dotenv import load_dotenv
load_dotenv()

# LangSmith Settings
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "Agent Verify Upstream (Fast)"

# Import Agent
from e2e_agent import upper_stream_agent_executor, UpperAgentState, upper_stream_tools
from langchain_core.messages import HumanMessage
from langchain_core.tools import Tool

# 1. create logic to patch the search tool
def mock_search_run(*args, **kwargs):
    print(f"\n[MOCK] Check args: {args} {kwargs}")
    run_dir = "/tmp/mock_search_run"
    if os.path.exists(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    
    # Create dummy papers
    for i in range(3):
        with open(f"{run_dir}/paper_{i}.json", "w") as f:
            json.dump({
                "title": f"Mock Paper {i}",
                "abstract": f"This is a mock abstract for paper {i} which mentions DBPs.",
                "source": "Mock"
            }, f)
            
    return f"Total Papers Found: 3. Run_dir: {run_dir}"

# 2. Patch the tool in the executor's tool list?
# The executor uses the tools passed to create_react_agent.
# We can't easily patch the executor internals, but we can patch the tool input's _run method?
# OR we can patch the tool instance in place if we can find it.

search_tool = [t for t in upper_stream_tools if t.name == "fulltext_journal_search"][0]
search_tool._run = mock_search_run

def test_workflow_fast():
    print("--- Testing Upstream Workflow (FAST MOCK) ---")
    query = "Find disinfection byproducts."
    
    state = {
        "messages": [HumanMessage(content=query)],
        "original_query": query,
        "search_session_dir": "/tmp/test_session",
        "iteration_count": 0
    }
    
    config = {"configurable": {"search_session_dir": "/tmp/test_session", "thread_id": "fast_test_1"}}
    
    print("Invoking Agent...")
    try:
        result = upper_stream_agent_executor.invoke(state, config=config)
        messages = result["messages"]
        
        # Verify
        tool_calls = []
        for m in messages:
            if hasattr(m, "tool_calls") and m.tool_calls:
                for tc in m.tool_calls:
                    print(f"Tool Call: {tc['name']}")
                    tool_calls.append(tc['name'])
        
        if "fulltext_journal_search" in tool_calls and "inspect_search_results" in tool_calls:
            print("\n✅ SUCCESS: Agent called Search -> Inspect.")
        else:
            print("\n❌ FAILURE: Missing calls.")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_workflow_fast()
