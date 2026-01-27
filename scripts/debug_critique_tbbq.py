
import sys
import json
import os
from langchain_community.chat_models import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from dotenv import load_dotenv

# Setup paths
BASE_DIR = "/home/chen/GNPS_SIM/agent/db_form_agent_system"
load_dotenv(os.path.join(BASE_DIR, ".env")) # Load Env

PROMPT_PATH = os.path.join(BASE_DIR, "prompts/critique_agent.md")
PAPER_PATH = "/home/chen/GNPS_SIM/agent/searching_results/dbp_eval_eval_fd2d1fef/--13.json"

# Load Prompt
with open(PROMPT_PATH, "r") as f:
    system_prompt_template = f.read()

# Load Paper
with open(PAPER_PATH, "r") as f:
    paper = json.load(f)

# Construct specific inputs
# The agent usually gets: target_compound, found_evidence (list of snippets)
target_compound = "2,3,5,6-Tetrabromocyclohexa-2,5-diene-1,4-dione"
evidence_text = f"Title: {paper.get('title')}\nContent: {paper.get('full_text')}"

# Helper to format the prompt (mimicking e2e_agent.py or critique_agent logic)
# In e2e_agent.py, we might replace placeholders.
# Let's check if the prompt has {{target}} or similar.
# Assuming standard formatting:
system_prompt = system_prompt_template.replace("{{target}}", target_compound) # Hypothesis
# Actually, usually the input is passed in the User Message or the System Prompt is static.
# Let's look at the System Prompt first to be sure, but standard agent logic usually passes context in User Message.
# I will use a generic "Here is the evidence" user message format if I can't verify exact injection.

# Inspect prompt to see placeholders
if "{{" in system_prompt_template:
    print("Found placeholders in prompt, attempting to fill...")
    # This is a guess, I should check e2e_agent.py but for now specific tbbq name is key.
    pass

# Initialize LLM with OpenRouter Base URL
# Check if key starts with sk-or (OpenRouter)
api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
base_url = None
if api_key and api_key.startswith("sk-or"):
    base_url = "https://openrouter.ai/api/v1"

llm = ChatOpenAI(
    model="gpt-4o", 
    temperature=0,
    openai_api_key=api_key,
    openai_api_base=base_url
)

# Construct Messages
# Based on typical flow: 
# System: Role definitions
# User: "Review this evidence for [Compound]: [Snippets]"
user_content = f"""
Target Compound: {target_compound}

Retrieved Evidence:
[1] {evidence_text}

Verify if the compound is a confirmed Disinfection By-Product (DBP).
"""

messages = [
    SystemMessage(content=system_prompt_template),
    HumanMessage(content=user_content)
]

print("--- Sending Request to Critique Agent ---")
print(f"Target: {target_compound}")
print(f"Evidence Length: {len(evidence_text)}")
print("---")

try:
    response = llm.invoke(messages)
    print("--- Response ---")
    print(response.content)
except Exception as e:
    print(f"Error: {e}")
