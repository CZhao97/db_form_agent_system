#!/usr/bin/env python3
"""
NER vs LLM Cost & Extraction Benchmark (OpenRouter Gemini 2.5 Flash)
Optimized for Long Context (No Chunking)
"""

import sys
print(f"DEBUG_PYTHON: {sys.executable}")
import os
import json
import time
import logging
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, Any, List, Tuple, Optional
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from matplotlib.ticker import FuncFormatter

# =========================
# CONFIG
# =========================
SEARCH_RESULTS_DIR = "agent/searching_results/e2e_run_20260125_130247/literature_searching"
DOTENV_PATH = ".env"

# Target files (valid existing files with NER caches)
TARGET_FILES = [
    "10.1039d4ra04328f_hydrated.json",
]

# Output files
OUT_CSV = "ner_vs_llm_comparison_fulltext.csv"
OUT_PLOT_SCATTER = "ner_vs_llm_scatter_fulltext.png"

# =========================
# PRICING (USD per 1M Tokens) - 2026 Rates
# =========================
# NER (Simulated using Gemini 2.5 Flash Tokens)
NER_INPUT_TOKENS = 3235  # Abstract + Prompt
NER_OUTPUT_TOKENS = 3330 # Verbose Tool Call Arguments

# Pricing for Gemini 2.5 Flash (USD per 1M Tokens)
PRICE_FLASH_IN_PER_1M = 0.10
PRICE_FLASH_OUT_PER_1M = 0.40

# Assign NER Baseline Cost using Flash Pricing
PRICE_NER_IN_PER_1M = PRICE_FLASH_IN_PER_1M
PRICE_NER_OUT_PER_1M = PRICE_FLASH_OUT_PER_1M

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("ner_vs_llm_benchmark")

# =========================
# HELPERS
# =========================
def load_env_key() -> Optional[str]:
    load_dotenv(DOTENV_PATH)
    return os.getenv("OPENROUTER_API_KEY")

def safe_read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Failed to read JSON: {path} | {e}")
        return None

def normalize_chem(s: str) -> str:
    s = str(s).strip().lower()
    if " (context:" in s:
        s = s.split(" (context:", 1)[0].strip()
    return " ".join(s.split())

def load_ner_results(json_filename: str) -> List[str]:
    base_path = os.path.join(SEARCH_RESULTS_DIR, json_filename)
    cache_path = base_path.replace(".json", ".ner_cache.json")
    if not os.path.exists(cache_path): return []
    data = safe_read_json(cache_path)
    if not data: return []
    
    if "merged_output" in data: data = data["merged_output"]
    chems = set()
    if isinstance(data, dict):
        for details in data.values():
            if isinstance(details, dict):
                for m in details.get("mentions", []):
                    if isinstance(m, str): chems.add(normalize_chem(m))
                    elif isinstance(m, dict): chems.add(normalize_chem(m.get("text", "")))
    return sorted(list(chems))

def extract_usage(ai_msg) -> Tuple[int, int]:
    if hasattr(ai_msg, "usage_metadata"):
        return ai_msg.usage_metadata.get("input_tokens", 0), ai_msg.usage_metadata.get("output_tokens", 0)
    # Fallback for standard LangChain metadata
    meta = getattr(ai_msg, "response_metadata", {})
    usage = meta.get("token_usage", meta.get("usage", {}))
    return usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)

def parse_json_only(text: str) -> Optional[Dict[str, Any]]:
    try:
        l, r = text.find("{"), text.rfind("}")
        return json.loads(text[l:r+1]) if l != -1 else None
    except: return None

def dollars_from_tokens(pt: int, ct: int, p_in: float, p_out: float) -> float:
    return (pt * p_in + ct * p_out) / 1_000_000.0

# =========================
# CORE EXTRACTION
# =========================
def llm_extract_full_text(llm: ChatOpenAI, text: str) -> Tuple[List[str], int, int]:
    prompt = (
        "You are a specialized chemistry assistant. Extract ALL chemical entities from the following text.\n"
        "Return the result ONLY as a JSON object with a 'chemicals' key containing a list of strings.\n"
        "Rules: Include compounds, materials, solvents, and drugs. Deduplicate.\n\n"
        f"TEXT:\n{text}"
    )
    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        pt, ct = extract_usage(resp)
        data = parse_json_only(resp.content)
        if data and "chemicals" in data:
            return [normalize_chem(c) for c in data["chemicals"] if c], pt, ct
    except Exception as e:
        log.error(f"Extraction failed: {e}")
    return [], 0, 0

def main():
    api_key = load_env_key()
    if not api_key: return

    llm = ChatOpenAI(
        model="google/gemini-2.5-flash", 
        openai_api_key=api_key,
        openai_api_base="https://openrouter.ai/api/v1",
        temperature=0,
    )

    results = []
    cost_ner_usd = dollars_from_tokens(NER_INPUT_TOKENS, NER_OUTPUT_TOKENS, PRICE_GPT4O_IN_PER_1M, PRICE_GPT4O_OUT_PER_1M)

    for filename in TARGET_FILES:
        filepath = os.path.join(SEARCH_RESULTS_DIR, filename)
        doc_data = safe_read_json(filepath)
        if not doc_data: continue

        full_text = doc_data.get("full_text", "")
        if len(str(full_text)) < 500: # Fallback to abstract
            full_text = f"{doc_data.get('title', '')} {doc_data.get('abstract', '')}"

        log.info(f"Processing {filename} ({len(full_text)} chars) in single pass...")
        
        # LLM Extraction (Single Pass - Full Context)
        llm_chems, pt, ct = llm_extract_full_text(llm, full_text)
        ner_chems = load_ner_results(filename)
        
        cost_flash = dollars_from_tokens(pt, ct, PRICE_FLASH_IN_PER_1M, PRICE_FLASH_OUT_PER_1M)
        
        results.append({
            "filename": filename,
            "ner_count": len(ner_chems),
            "flash_count": len(llm_chems),
            "cost_ner": cost_ner_usd,
            "cost_flash": cost_flash,
            "tokens_in": pt,
            "tokens_out": ct
        })

    # Save & Plot
    df = pd.DataFrame(results)
    df.to_csv(OUT_CSV, index=False)
    
    # Visualization
    plt.figure(figsize=(10, 6))
    plot_data = pd.concat([
        df.rename(columns={"ner_count": "Count", "cost_ner": "Cost"}).assign(Method="NER (Fixed GPT-4o)"),
        df.rename(columns={"flash_count": "Count", "cost_flash": "Cost"}).assign(Method="Gemini 2.5 Flash")
    ])
    sns.scatterplot(data=plot_data, x="Count", y="Cost", hue="Method", s=200)
    plt.yscale("log")
    plt.gca().yaxis.set_major_formatter(FuncFormatter(lambda y, _: f'${y:.4f}'))
    plt.title("Benchmarking: Extraction Yield vs. Cost (Full Context Analysis)")
    plt.grid(True, which="both", ls="--", alpha=0.5)
    plt.savefig(OUT_PLOT_SCATTER, dpi=300)
    log.info(f"Done. Results saved to {OUT_CSV} and {OUT_PLOT_SCATTER}")

if __name__ == "__main__":
    main()