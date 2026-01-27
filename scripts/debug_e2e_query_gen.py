
import sys
import os
from pathlib import Path
import time
import json

# Add paths to make imports work
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir / "notebooks"))
sys.path.append(str(root_dir / "code"))

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

# Import from e2e_agent
try:
    from e2e_agent import (
        FullWorkflowState, 
        refinement_agent_node, 
        human_feedback_node, 
        upper_stream_agent_node, 
        query_generation_node, 
        should_continue_refinement,
        upper_should_continue,
        REFINEMENT_PROMPT,
        upper_stream_memory,
    )
except ImportError as e:
    print(f"Error importing e2e_agent: {e}")
    sys.exit(1)

def run_debug(query):
    print(f"🚀  Running e2e agent [Query Gen ONLY] for: '{query}'")
    
    # 1. Define Modified Workflow
    workflow = StateGraph(FullWorkflowState)
    workflow.add_node("refinement_agent", refinement_agent_node)
    workflow.add_node("human_feedback", human_feedback_node)
    workflow.add_node("upper_stream_agent", upper_stream_agent_node)
    workflow.add_node("query_generation", query_generation_node)

    workflow.set_entry_point("refinement_agent")

    workflow.add_conditional_edges(
        "refinement_agent",
        should_continue_refinement,
        {
            "human_feedback": "human_feedback",
            "upper_stream_agent": "upper_stream_agent"
        }
    )
    workflow.add_edge("human_feedback", "refinement_agent")

    workflow.add_conditional_edges(
        "upper_stream_agent",
        upper_should_continue,
        {
            "agent": "upper_stream_agent",
            END: "query_generation",
        },
    )

    # STOP HERE: Instead of downstream_batch, go to END
    workflow.add_edge("query_generation", END)

    app = workflow.compile(checkpointer=upper_stream_memory)

    # 2. Config & Input
    run_timestamp = time.strftime("%Y%m%d_%H%M%S")
    thread_id = f"debug_qgen_{run_timestamp}"
    # Use standard results dir structure
    session_dir = root_dir / "agent" / "searching_results" / f"e2e_run_{run_timestamp}"
    literature_dir = session_dir / "literature_searching"
    literature_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📂 Session: {session_dir}")
    
    config = {
        "configurable": {"thread_id": thread_id, "search_session_dir": str(literature_dir)},
        "recursion_limit": 100
    }
    
    input_state = {
        "messages": [HumanMessage(content=query)],
        "original_query": query,
        "search_session_dir": str(literature_dir),
        "iteration_count": 0,
        "refinement_messages": [
            SystemMessage(content=REFINEMENT_PROMPT),
            HumanMessage(content=f"User Query: {query}")
        ],
        "is_satisfied": False,
        "downstream_states": [],
        "downstream_configs": [],
        "final_reports": []
    }
    
    # 3. Run
    try:
        final_state = app.invoke(input_state, config=config)
        
        # 4. Inspect Results
        ds_states = final_state.get('downstream_states', [])
        print(f"\n\n✅ Query Generation Complete. Generated {len(ds_states)} downstream tasks.")
        
        if ds_states:
            print("\n--- Sample Queries ---")
            for i, ds in enumerate(ds_states[:5]):
                print(f"{i+1}. {ds['original_query']}")
            
            # Save for inspection
            output_file = session_dir / "generated_queries.json"
            queries = [ds['original_query'] for ds in ds_states]
            with open(output_file, "w") as f:
                json.dump(queries, f, indent=2)
            print(f"\n📄 Saved all queries to: {output_file}")
            
    except Exception as e:
        print(f"\n❌ Execution Error: {e}")

if __name__ == "__main__":
    # Default query from e2e_agent
    target_query = "Form a database of all experimentally confirmed disinfection byproducts (DBPs)"
    run_debug(target_query)
