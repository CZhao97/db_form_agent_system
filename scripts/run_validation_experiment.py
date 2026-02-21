
import os
import json
import random
import glob
import logging
import time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Setup env
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

class ChatOpenRouter(ChatOpenAI):
    def __init__(self, openai_api_key=None, **kwargs):
        super().__init__(base_url="https://openrouter.ai/api/v1", openai_api_key=openai_api_key, **kwargs)

def load_ner_cache(file_path):
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        if "merged_output" in data:
            return data["merged_output"]
        if "per_file_results" in data:
             merged = {}
             for f_entry in data["per_file_results"]:
                 for k, v in f_entry.get("entities", {}).items():
                     if k not in merged:
                         merged[k] = {"synonyms": v.get("synonyms", []), "mentions": v.get("mentions", [])}
                     else:
                         merged[k]["mentions"].extend(v.get("mentions", []))
             return merged
        if isinstance(data, dict) and len(data) > 0:
            sample_val = next(iter(data.values()))
            if isinstance(sample_val, dict) and ("mentions" in sample_val or "synonyms" in sample_val):
                return data
        return {}
    except Exception as e:
        log.error(f"Error loading {file_path}: {e}")
        return {}

def process_paper(pipeline_args):
    """Worker function for threading"""
    paper_dir, cache_files, system_prompt, original_query, model_config = pipeline_args
    
    # Initialize model inside worker (or share if thread-safe, ChatOpenAI is usually fine but let's be safe)
    # Actually, initializing per request is safer for simple scripts
    model = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0, openai_api_key=model_config["api_key"])
    
    # Merge entities
    merged_entities = {}
    for fpath in cache_files:
        file_data = load_ner_cache(fpath)
        for k, v in file_data.items():
            if k not in merged_entities:
                merged_entities[k] = {"synonyms": set(v.get("synonyms", [])), "mentions": v.get("mentions", [])}
            else:
                merged_entities[k]["synonyms"].update(v.get("synonyms", []))
                merged_entities[k]["mentions"].extend(v.get("mentions", []))
    
    if not merged_entities:
        return None

    # Sample
    all_keys = list(merged_entities.keys())
    sample_size = min(200, len(all_keys))
    # Note: Using python's random inside thread is fine
    sampled_keys = random.sample(all_keys, sample_size)
    
    entity_data = []
    for kid in sampled_keys:
        val = merged_entities[kid]
        names = list(val["synonyms"])
        mentions = val["mentions"][:5]
        entity_data.append({
            "id": kid,
            "names": names,
            "mentions": mentions
        })
        
    input_payload = {
        "original_query": original_query,
        "entity_data": entity_data
    }
    
    try:
        start_t = time.time()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=json.dumps(input_payload))
        ]
        response = model.invoke(messages)
        duration = time.time() - start_t
        
        # Parse
        queries = []
        accepted_ids = []
        content = response.content
        import re
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            json_out = json.loads(match.group(0))
            queries = json_out.get("queries", [])
            accepted_ids = json_out.get("accepted_ids", [])
            
        return {
            "paper": paper_dir,
            "input_count": len(entity_data),
            "accepted_count": len(accepted_ids),
            "query_count": len(queries),
            "duration": duration,
            "accepted_ids": accepted_ids,
            "queries": queries
        }
    except Exception as e:
        log.error(f"Error processing {paper_dir}: {e}")
        return None

def run_experiment(n_papers=50, seed=42):
    random.seed(seed)
    log.info(f"Starting Multi-threaded Validation Experiment on {n_papers} papers (Seed={seed})...")
    
    output_file = "validation_results.jsonl"
    # Clear output file
    with open(output_file, 'w') as f:
        pass

    # 1. Discovery
    base_dir = "agent/searching_results/ablation_study"
    files = glob.glob(os.path.join(base_dir, "**", "*.ner_cache.json"), recursive=True)
    paper_map = defaultdict(list)
    for f in files:
        paper_map[os.path.dirname(f)].append(f)
    papers = list(paper_map.keys())
    
    # 2. Sample
    if len(papers) > n_papers:
        selected_papers = random.sample(papers, n_papers)
    else:
        selected_papers = papers
        
    # 3. Setup
    prompt_path = Path("prompts/query_generator_agent.md")
    system_prompt = prompt_path.read_text(encoding="utf-8")
    original_query = (
        "Identify experimentally confirmed 'disinfection byproducts' (DBPs) formed during water treatment. "
        "Exclude theoretical predictions, solvents, reagents, or unconfirmed suspects."
    )
    model_config = {"api_key": OPENROUTER_API_KEY}
    
    # 4. Execute
    tasks = []
    for p in selected_papers:
        tasks.append((p, paper_map[p], system_prompt, original_query, model_config))
        
    completed = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_paper, t) for t in tasks]
        
        with open(output_file, 'a') as f:
            for future in as_completed(futures):
                result = future.result()
                completed += 1
                if result:
                    f.write(json.dumps(result) + "\n")
                    f.flush()
                    log.info(f"[{completed}/{n_papers}] Processed {result['paper']} -> In: {result['input_count']}, Acc: {result['accepted_count']}")
                else:
                    log.warning(f"[{completed}/{n_papers}] Failed or empty result.")

    log.info(f"Done. Results in {output_file}")

if __name__ == "__main__":
    run_experiment()
