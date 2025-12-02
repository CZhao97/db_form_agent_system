import sys
import os
import json
import re
import logging
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field, SecretStr
from langchain_core.utils.utils import secret_from_env

# Add code dir to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../code'))
from ner_results_viewer import load_ner_results, ner_results_to_dataframe

load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s | %(message)s')
log = logging.getLogger("test_query_generator")

# Constants
PROMPTS_DIR = Path("/home/chen/GNPS_SIM/agent/db_form_agent_system/prompts")
NER_RESULTS_FILE = "/home/chen/GNPS_SIM/agent/db_form_agent_system/searching_results/e2e_run_20251126_134614/literature_searching/ner_results/chemical_ner_results.json"
OUTPUT_FILE = "generated_queries.json"

# ChatOpenRouter Class
class ChatOpenRouter(ChatOpenAI):
    openai_api_key: Optional[SecretStr] = Field(
        alias="api_key", default_factory=secret_from_env("OPENROUTER_API_KEY", default=None)
    )
    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"openai_api_key": "OPENROUTER_API_KEY"}

    def __init__(self,
                 openai_api_key: Optional[str] = None,
                 **kwargs):
        openai_api_key = openai_api_key or os.environ.get("OPENROUTER_API_KEY")
        super().__init__(base_url="https://openrouter.ai/api/v1", openai_api_key=openai_api_key, **kwargs)

def main():
    if not Path(NER_RESULTS_FILE).exists():
        log.error(f"NER results file not found: {NER_RESULTS_FILE}")
        return

    log.info(f"Loading NER results from: {NER_RESULTS_FILE}")
    
    # Load NER results
    ner_data = load_ner_results(NER_RESULTS_FILE)
    df = ner_results_to_dataframe(ner_data, include_synonyms=False)
    
    if df.empty:
        log.warning("No chemical entities found in NER results.")
        return

    # Select chemicals (taking top 10 for testing)
    sample_size = min(100, len(df))
    top_chemicals = df.sample(n=sample_size)
    
    chemical_names = []
    for entry in top_chemicals['unique_mentions']:
        if isinstance(entry, str):
            chemical_names.append([name.strip() for name in entry.split(',') if name.strip()])

    if not chemical_names:
        log.warning("No chemical name clusters found.")
        return

    log.info("Selected chemical clusters:")
    for cluster in chemical_names:
        log.info(f"  - {cluster}")

    # Prepare LLM input
    original_query = "Form a database of all experimentally confirmed disinfection byproducts (DBPs)" # Assumed context
    input_content = json.dumps({
        "original_query": original_query,
        "chemical_names": chemical_names
    })

    # Initialize Model and Prompt
    query_generator_model = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0)
    QUERY_GENERATOR_PROMPT_PATH = PROMPTS_DIR / "query_generator_agent.md"
    
    if not QUERY_GENERATOR_PROMPT_PATH.exists():
        log.error(f"Prompt file not found: {QUERY_GENERATOR_PROMPT_PATH}")
        return

    QUERY_GENERATOR_PROMPT = SystemMessage(content=QUERY_GENERATOR_PROMPT_PATH.read_text(encoding="utf-8"))
    
    log.info("Invoking Query Generator Agent...")
    message = HumanMessage(content=input_content)
    response = query_generator_model.invoke([QUERY_GENERATOR_PROMPT, message])
    
    # Parse Output
    try:
        match = re.search(r'\{[\s\S]*\}', response.content)
        if not match:
            raise json.JSONDecodeError("No JSON object found in LLM response.", response.content, 0)
        output_json = json.loads(match.group(0))
        downstream_queries = output_json.get("queries", [])
        
        log.info(f"Generated {len(downstream_queries)} queries.")

        # Map queries back to chemical clusters
        final_output = {}
        
        for query in downstream_queries:
            best_match_cluster = None
            best_match_score = 0
            best_match_name = ""
            
            # Iterate through all clusters to find which one is mentioned in the query
            for cluster in chemical_names:
                for name in cluster:
                    # Check if name is in query (case insensitive)
                    # Use simple inclusion for now, could be improved with regex for word boundaries
                    if name.lower() in query.lower():
                        # Prefer longer matches (e.g. "acetic acid" over "acid")
                        if len(name) > best_match_score:
                            best_match_score = len(name)
                            best_match_cluster = cluster
                            best_match_name = cluster[0] # Use first name as key
            
            if best_match_cluster:
                final_output[best_match_name] = [query, best_match_cluster]
            else:
                log.warning(f"Could not map query to any chemical cluster: {query}")
        
        # Save to file
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(final_output, f, indent=2)
        log.info(f"Saved generated queries to {OUTPUT_FILE}")
        
        # Print queries
        print(json.dumps(final_output, indent=2))

    except Exception as e:
        log.error(f"Failed to parse output: {e}")
        log.error(f"Raw output: {response.content}")

if __name__ == "__main__":
    main()
