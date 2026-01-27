
import sys
import json
import os
from langchain_community.chat_models import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from dotenv import load_dotenv

# Setup paths
BASE_DIR = "/home/chen/GNPS_SIM/agent/db_form_agent_system"
load_dotenv(os.path.join(BASE_DIR, ".env")) 

PROMPT_PATH = os.path.join(BASE_DIR, "prompts/literature_agent.md")

# Load Prompt
with open(PROMPT_PATH, "r") as f:
    system_prompt_template = f.read()

# Initialize LLM
api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
base_url = None
if api_key and api_key.startswith("sk-or"):
    base_url = "https://openrouter.ai/api/v1"

llm = ChatOpenAI(
    model="gpt-4o", 
    temperature=0, # Deterministic check
    openai_api_key=api_key,
    openai_api_base=base_url
)

target_compound = "2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione"

user_content = f"""
Current Objective: Determine if '{target_compound}' is a known Disinfection By-Product (DBP) in water treatment.

Instruction: Generate search queries to find evidence. Return JSON.
"""

messages = [
    SystemMessage(content=system_prompt_template),
    HumanMessage(content=user_content)
]

print("--- Sending Request to Researcher Agent (Query Generation) ---")
print(f"Target: {target_compound}")

try:
    response = llm.invoke(messages)
    print("--- Response ---")
    print(response.content)
except Exception as e:
    print(f"Error: {e}")
