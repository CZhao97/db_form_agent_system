
import os
import json
import logging
import sys
import re
import math
from pathlib import Path
import warnings
import time

# Suppress warnings
warnings.filterwarnings("ignore")

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger("batch_query_gen")

# Add code dir to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../agent/code'))
# langgraph imports mock
import os
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr
from typing import Optional

# Mock the environment setup from e2e_agent
from dotenv import load_dotenv
load_dotenv()

class ChatOpenRouter(ChatOpenAI):
    openai_api_key: Optional[SecretStr] = Field(
        alias="api_key", default_factory=None
    )
    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"openai_api_key": "OPENROUTER_API_KEY"}

    def __init__(self,
                 openai_api_key: Optional[str] = None,
                 **kwargs):
        openai_api_key = openai_api_key or os.environ.get("OPENROUTER_API_KEY")
        super().__init__(base_url="https://openrouter.ai/api/v1", openai_api_key=openai_api_key, **kwargs)

def run_batch_generation():
    run_timestamp = time.strftime("%Y%m%d_%H%M%S")
    os.environ["LANGCHAIN_PROJECT"] = f"Query Generation Agent Run - {run_timestamp}"
    # Paths
    BASE_DIR = Path("/home/chen/GNPS_SIM/agent/db_form_agent_system")
    NER_RESULTS_FILE = BASE_DIR / "agent/searching_results/e2e_run_20260125_130247/literature_searching/chemical_ner_results.json"
    OUTPUT_FILE = BASE_DIR / "agent/searching_results/e2e_run_20260125_130247/recovered_queries_full.json"
    PROMPTS_DIR = BASE_DIR / "prompts"
    
    # Check input
    if not NER_RESULTS_FILE.exists():
        log.error(f"Input file not found: {NER_RESULTS_FILE}")
        return

    # Load data
    log.info(f"Loading NER results from {NER_RESULTS_FILE}...")
    with open(NER_RESULTS_FILE, 'r') as f:
        ner_data = json.load(f)

    # Extract all relevant mentions/clusters
    # Logic extracted from e2e_agent.py
    # We prefer "top_chemicals" logic but for *all* chemicals
    
    merged_output = ner_data.get("merged_output", {})
    if not merged_output and ner_data.get("per_file_results"):
         # Aggregate on the fly if needed (copied from e2e_agent)
         log.info("Aggregating per-file results...")
         aggregated = {}
         for file_entry in ner_data["per_file_results"]:
             entities = file_entry.get("entities", {})
             for kb_id, details in entities.items():
                 if kb_id not in aggregated:
                     aggregated[kb_id] = {"mentions": [], "synonyms": details.get("synonyms", [])}
                 aggregated[kb_id]["mentions"].extend(details.get("mentions", []))
         
         final_aggregated = {}
         for kb_id, data in aggregated.items():
             unique = sorted(list(set(data["mentions"])))
             final_aggregated[kb_id] = {"synonyms": data["synonyms"], "mentions": [{"text": unique}]}
         merged_output = final_aggregated

    # Convert to flat list of name inputs
    # e2e_agent expects a list of lists: [["Name", "Context"], ...]
    # We will iterate through merged_output
    
    all_input_clusters = []
    
    # We need to mimic ner_results_to_dataframe logic roughly or just take the raw mentions
    # e2e_agent: entry['unique_mentions'] -> list of strings
    
    for kb_id, data in merged_output.items():
        # data["mentions"] is list of dicts with "text" list
        # We flatten it to a single list of strings
        mentions = []
        for m_grp in data.get("mentions", []):
            if isinstance(m_grp, dict):
                mentions.extend(m_grp.get("text", []))
            elif isinstance(m_grp, list):
                mentions.extend(m_grp)
        
        # Deduplicate and clean
        unique_mentions = list(set([m for m in mentions if m and isinstance(m, str)]))
        # LIMIT CONTEXT SIZE: Take only first 10 mentions to avoid token explosion
        if len(unique_mentions) > 10:
            unique_mentions = unique_mentions[:10]
            
        if unique_mentions:
            all_input_clusters.append(unique_mentions)
            
    total_chemicals = len(all_input_clusters)
    log.info(f"Found {total_chemicals} unique chemical clusters.")
    
    if total_chemicals == 0:
        log.warning("No chemicals found.")
        return

    # Batch config
    BATCH_SIZE = 50 # Safe size for context
    batches = math.ceil(total_chemicals / BATCH_SIZE)
    log.info(f"Processing in {batches} batches of {BATCH_SIZE}...")

    # Load Prompt
    QUERY_GENERATOR_PROMPT_PATH = PROMPTS_DIR / "query_generator_agent.md"
    prompt_content = QUERY_GENERATOR_PROMPT_PATH.read_text(encoding="utf-8")
    SYSTEM_PROMPT = SystemMessage(content=prompt_content)
    
    # Setup Model
    llm = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0)
    
    # Original Query (Hardcoded from user context or typical usage)
    # Ideally checking state, but we'll use a recovered definition
    # We will try to read the definition from the e2e_agent context or prompt user?
    # Actually, in the user's JSON input (that failed), they provided "original_query".
    # I will stick usage of a standard query or try to extract it from context.
    # User's pasted JSON had: "Form a database of all experimentally confirmed disinfection byproducts (DBPs)"
    # But e2e_agent also injects "refined_definition".
    
    # Let's use a generic strong query or the one from the recovering text
    # The recovery script used:
    original_query = "Form a database of all experimentally confirmed disinfection byproducts (DBPs)"
    refined_definition = (
        "A confirmed disinfection byproduct (DBP) is any compound that is formed during drinking-water–relevant disinfection or oxidation processes (e.g., chlorination, chloramination, bromination, ozonation, UV, PMS, etc.) of natural organic matter or anthropogenic organic precursors (e.g., pharmaceuticals, contrast media, pesticides, bisphenol A, triclosan, etc.)"
    )
    
    # Output file (JSONL for incremental saving)
    # BATCH TRACKING FILE
    BATCH_LOG_FILE = BASE_DIR / "agent/searching_results/e2e_run_20260125_130247/batch_progress.log"
    
    # Resume Logic
    completed_batches = set()
    if BATCH_LOG_FILE.exists():
        with open(BATCH_LOG_FILE, 'r') as f:
            for line in f:
                if line.strip().isdigit():
                    completed_batches.add(int(line.strip()))
    
    log.info(f"Resume: Found {len(completed_batches)} completed batches.")

    all_downstream_queries = []
    
    for i in range(batches):
        if i in completed_batches:
            continue
            
        start_idx = i * BATCH_SIZE

        end_idx = min((i + 1) * BATCH_SIZE, total_chemicals)
        batch_clusters = all_input_clusters[start_idx:end_idx]
        
        log.info(f"Processing batch {i+1}/{batches} (Indices {start_idx}-{end_idx})...")
        
        input_data = {
            "original_query": original_query,
            "chemical_names": batch_clusters,
            "refined_definition": refined_definition,
            "instruction": (
                "Filter the provided chemical clusters based on the definition and context. "
                "Return a JSON object with: \n"
                "1. 'candidates': A list of the filtered, canonical chemical names.\n"
                "2. 'demo_query': A single full example query for the FIRST candidate only, following the template rules.\n"
                "Do NOT generate full queries for the other candidates."
            )
        }
        
        input_content = json.dumps(input_data)
        message = HumanMessage(content=input_content)
        
        try:
            response = llm.invoke([SYSTEM_PROMPT, message])
            
            # Parse response
            match = re.search(r'\{[\s\S]*\}', response.content)
            if match:
                output_json = json.loads(match.group(0))
                candidates = output_json.get("candidates", [])
                demo_query = output_json.get("demo_query", "")
                
                if demo_query and i == 0:
                    log.info(f"  -> [DEMO QUERY from LLM]: {demo_query[:200]}...") 
                    # Save demo query to file for user inspection
                    with open(BASE_DIR / "agent/searching_results/e2e_run_20260125_130247/demo_query.txt", "w") as dqf:
                        dqf.write(demo_query)
                
                # Manual Template Injection
                generated_queries = []
                for chemical in candidates:
                    query_text = (
                        f"According to the following definition, decide whether '{chemical}' is a 'experimentally confirmed disinfection byproduct (DBP)':\n"
                        f"{refined_definition}\n\n"
                        f"Based on the peer-reviewed literature, is '{chemical}' a 'experimentally confirmed disinfection byproduct (DBP)' under this definition?"
                    )
                    generated_queries.append(query_text)

                # Append to JSONL immediately
                with open(OUTPUT_FILE, 'a') as f:
                    for q in generated_queries:
                        f.write(json.dumps({"query": q}) + "\n")
                        
                log.info(f"  -> Extracted {len(candidates)} candidates. Generated {len(generated_queries)} queries. Saved to {OUTPUT_FILE}")
            else:
                log.error(f"  -> Failed to find JSON in batch {i}")
                log.debug(response.content[:500])
                
            # Log completion of this batch
            with open(BATCH_LOG_FILE, 'a') as f:
                f.write(f"{i}\n")
                
        except Exception as e:
            log.error(f"  -> Error in batch {i}: {e}")
            
    log.info("Done.")

if __name__ == "__main__":
    run_batch_generation()
