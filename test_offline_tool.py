import sys
import os
import json

# Add code directory to path
sys.path.append(os.path.join(os.getcwd(), 'code'))

from offline_paper_tool import OfflinePaperSearchTool

def test_tool():
    print("Initializing OfflinePaperSearchTool...")
    # Point to the index we created
    tool = OfflinePaperSearchTool(index_path="./pmc_lancedb_index")
    
    query = "chronic pain"
    print(f"Running query: '{query}'")
    
    result_json = tool.run({"query": query, "k": 2})
    
    try:
        results = json.loads(result_json)
        print(f"Received {len(results)} results.")
        for i, res in enumerate(results):
            print(f"\nResult {i+1}:")
            print(f"  Title: {res.get('title')}")
            print(f"  Score: {res.get('score')}")
            print(f"  NER Keys: {list(res.get('ner', {}).keys())}")
    except json.JSONDecodeError:
        print("Failed to parse JSON output:")
        print(result_json)

if __name__ == "__main__":
    test_tool()
