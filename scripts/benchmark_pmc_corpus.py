
import os
import random
import glob
import time
import json
import logging
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from typing import List, Dict, Tuple, Set

# Imports for NER Tool
# Removed to avoid conflicts with LangChain/Pydantic
# from chemical_ner_tool import extract_chemicals_with_nen_batch
import sys

# Imports for LLM
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

# Constants
PMC_DIR = "/data/chen/pubmed_corpus/pmc_extracted_text/"
SAMPLE_SIZE = 5
OUT_CSV = "pmc_benchmark_results.csv"
OUT_PLOT = "pmc_benchmark_scatter.png"

# Pricing (Same as compare_ner_vs_llm.py)
PRICE_FLASH_IN_PER_1M = 0.10
PRICE_FLASH_OUT_PER_1M = 0.40
FIXED_NER_COST = 0.041  # Equivalent commercial API cost proxy

def load_env_key():
    load_dotenv()
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        log.error("OPENROUTER_API_KEY not found in env.")
    return key

def normalize_chem(chem: str) -> str:
    return chem.strip().lower().rstrip("s").rstrip("es")

def get_random_files(directory: str, count: int) -> List[str]:
    files = glob.glob(os.path.join(directory, "*.txt"))
    if len(files) < count:
        log.warning(f"Only found {len(files)} files in {directory}. Using all.")
        return files
    return random.sample(files, count)

import subprocess

def run_local_ner(files: List[str]) -> List[Set[str]]:
    """Runs the local NER tool via subprocess and returns a list of sets of unique chemicals."""
    log.info(f"Running NER on {len(files)} documents (isolated process)...")
    t0 = time.time()
    
    cmd = [sys.executable, "scripts/run_local_ner_wrapper.py"] + files
    try:
        # No capture_output so logs flow to console/stderr
        subprocess.run(cmd, check=True)
        
        # Read JSON from file
        with open("ner_output.json", "r", encoding="utf-8") as f:
            output_data = json.load(f)
            
        unique_counts = [set(item) for item in output_data]
        # Clean up
        if os.path.exists("ner_output.json"):
            os.remove("ner_output.json")
            
    except subprocess.CalledProcessError as e:
        log.error(f"NER Subprocess failed: {e}")
        return [set() for _ in files]
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse NER output file: {e}")
        return [set() for _ in files]
        

        
    t1 = time.time()
    log.info(f"NER finished in {t1-t0:.2f}s")
    return unique_counts

def llm_extract_full_text(llm: ChatOpenAI, text: str) -> Tuple[Set[str], int, int]:
    prompt = (
        "You are a specialized chemistry assistant. Extract ALL chemical entities from the following text.\n"
        "Return the result ONLY as a JSON object with a 'chemicals' key containing a list of strings.\n"
        "Rules: Include compounds, materials, solvents, and drugs. Deduplicate.\n\n"
        f"TEXT:\n{text}"
    )
    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        
        # Extract usage
        if hasattr(resp, "usage_metadata"):
            pt = resp.usage_metadata.get("input_tokens", 0)
            ct = resp.usage_metadata.get("output_tokens", 0)
        else:
            meta = getattr(resp, "response_metadata", {})
            usage = meta.get("token_usage", meta.get("usage", {}))
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)

        # Parse JSON
        content = resp.content
        l, r = content.find("{"), content.rfind("}")
        if l != -1:
            data = json.loads(content[l:r+1])
            if "chemicals" in data:
                # We normalize strings here to compare counts somewhat fairly
                # Note: LLM doesn't give MESH IDs, so we are comparing "Count of Unique Strings" vs "Count of Unique IDs/Strings"
                # This puts NER at a slight disadvantage if normalized string count is lower than separate IDs,
                # BUT usually IDs collapse synonyms so NER count should be LOWER (more conservative/accurate).
                # Actually, let's stick to normalized strings for LLM.
                return {normalize_chem(c) for c in data["chemicals"] if c}, pt, ct
    except Exception as e:
        import traceback
        log.error(f"LLM Extraction failed: {e}")
        traceback.print_exc()
    
    return set(), 0, 0

def dollars_from_tokens(pt, ct):
    return (pt / 1_000_000 * PRICE_FLASH_IN_PER_1M) + (ct / 1_000_000 * PRICE_FLASH_OUT_PER_1M)

def main():
    api_key = load_env_key()
    if not api_key: return

    # Setup LLM
    llm = ChatOpenAI(
        model="google/gemini-2.5-flash", 
        openai_api_key=api_key,
        openai_api_base="https://openrouter.ai/api/v1",
        temperature=0,
    )

    # Specific file list from user
    target_files = [
        "PMC10000014.txt", "PMC10000015.txt", "PMC10000017.txt", "PMC10000022.txt", "PMC10000023.txt",
        "PMC10000024.txt", "PMC10000025.txt", "PMC10000026.txt", "PMC10000027.txt", "PMC10000028.txt"
    ]
    
    files = [os.path.join(PMC_DIR, f) for f in target_files]
    # Filter for existing files
    files = [f for f in files if os.path.exists(f)]
    
    log.info(f"Selected {len(files)} files for benchmarking.")

    results = []
    
    # Read Texts
    texts = []
    filenames = []
    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            t = f.read()
            texts.append(t)
            filenames.append(os.path.basename(fpath))

    # 2. Run NER (Batch)
    log.info("Starting NER Benchmarking...")
    ner_chems_list = run_local_ner(files) # Pass file paths, not texts

    # 3. Run LLM (Sequential)
    log.info("Starting LLM Benchmarking...")
    for i, (filename, text) in enumerate(zip(filenames, texts)):
        log.info(f"Processing {filename} ({len(text)} chars) with LLM...")
        llm_chems, _, _ = llm_extract_full_text(llm, text)
        
        ner_set = ner_chems_list[i]
        
        # Format for CSV: pipe-separated sorted string
        ner_str = "|".join(sorted(list(ner_set)))
        llm_str = "|".join(sorted(list(llm_chems)))
        
        results.append({
            "filename": filename,
            "ner_entities": ner_str,
            "llm_entities": llm_str
        })
        log.info(f"  > NER: {len(ner_set)}, Flash: {len(llm_chems)}")

    # 4. Save Simplified CSV
    df = pd.DataFrame(results)
    df.to_csv("ner_vs_llm_entities.csv", index=False)
    log.info(f"Done. Saved to ner_vs_llm_entities.csv")

if __name__ == "__main__":
    main()
