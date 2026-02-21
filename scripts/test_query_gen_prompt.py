
import os
import json
import logging
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

# Setup minimal env
load_dotenv()
# Mock the necessary environment for ChatOpenRouter if needed, or just use ChatOpenAI with base_url
# Assuming e2e_agent logic for model connection
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

class ChatOpenRouter(ChatOpenAI):
    def __init__(self, openai_api_key=None, **kwargs):
        super().__init__(base_url="https://openrouter.ai/api/v1", openai_api_key=openai_api_key, **kwargs)

def test_query_generation():
    print("--- Testing Query Generator Prompt ---")
    
    # 1. Load the Output Prompt (Current Version)
    prompt_path = Path("prompts/query_generator_agent.md")
    if not prompt_path.exists():
        print(f"Error: {prompt_path} not found.")
        return
    
    system_prompt_text = prompt_path.read_text(encoding="utf-8")
    
    # 2. Prepare Mock Input Data
    original_query = (
        "Identify experimentally confirmed 'disinfection byproducts' (DBPs) formed during water treatment. "
        "Exclude theoretical predictions or unconfirmed suspects."
    )
    
    entity_data = [
        # Case 1: Strong Candidate (Should be KEPT)
        {
            "id": "MESH:C0001", 
            "names": ["Chloroform", "Trichloromethane"], 
            "mentions": ["Chloroform was favored in high pH conditions...", "Formation of TCM (Context: TCM was detected as the major DBP in all samples)"]
        },
        # Case 2: Artifact/Solvent (Should be DISCARDED)
        {
            "id": "MESH:D0002", 
            "names": ["Methanol", "MeOH"], 
            "mentions": ["The extract was dissolved in Methanol...", "mobile phase A was water/MeOH (Context: samples were analyzed using LC-MS with MeOH gradient)"]
        },
        # Case 3: Negative Control/Not Detected (Should be DISCARDED)
        {
            "id": "MESH:D0003", 
            "names": ["Benzene"], 
            "mentions": ["Benzene was not detected in any of the chlorinated samples.", "Limit of detection for Benzene (Context: Benzene < LOD)"]
        },
        # Case 4: Ambiguous/Complex Case (Should be KEPT if context supports DBP claim)
        {
            "id": "MESH:C0004",
            "names": ["2,6-DCTBQ", "2,6-dichloro-1,4-benzoquinone"],
            "mentions": ["2,6-DCTBQ (Context: A novel DBP, 2,6-dichloro-1,4-benzoquinone, was identified for the first time in this study)"]
        }
    ]
    
    input_data = {
        "original_query": original_query,
        "entity_data": entity_data
    }
    
    print(f"Input Entities: {len(entity_data)}")
    print("Sending request to LLM...")
    
    # 3. Call LLM
    try:
        model = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0, openai_api_key=OPENROUTER_API_KEY)
        messages = [
            SystemMessage(content=system_prompt_text),
            HumanMessage(content=json.dumps(input_data))
        ]
        
        response = model.invoke(messages)
        print("\n--- LLM Response ---")
        print(response.content)
        
        # 4. Basic Validation
        try:
             import re
             match = re.search(r'\{[\s\S]*\}', response.content)
             if match:
                 data = json.loads(match.group(0))
                 queries = data.get("queries", [])
                 print(f"\nGenerated Queries: {len(queries)}")
                 for q in queries:
                     print(f" - {q}")
                     
                 # Assertions
                 has_chloroform = any('Chloroform' in q or 'Trichloromethane' in q for q in queries)
                 has_methanol = any('Methanol' in q for q in queries)
                 has_benzene = any('Benzene' in q for q in queries)
                 has_dctbq = any('2,6-dichloro-1,4-benzoquinone' in q or '2,6-DCTBQ' in q for q in queries)
                 
                 print("\n--- Verdicts ---")
                 print(f"Chloroform (Expected: KDPT): {'✅ Kept' if has_chloroform else '❌ Dropped'}")
                 print(f"Methanol (Expected: DROPPED): {'✅ Dropped' if not has_methanol else '❌ Kept (Artifact Error)'}")
                 print(f"Benzene (Expected: DROPPED): {'✅ Dropped' if not has_benzene else '❌ Kept (Negative Error)'}")
                 print(f"2,6-DCTBQ (Expected: KEPT): {'✅ Kept' if has_dctbq else '❌ Dropped'}")
                 
             else:
                 print("Error: Could not extract JSON from response")
        except Exception as e:
            print(f"JSON Parsing Error: {e}")
            
    except Exception as e:
        print(f"LLM Call Error: {e}")

if __name__ == "__main__":
    test_query_generation()
