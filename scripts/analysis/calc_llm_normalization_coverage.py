
import json
import pandas as pd
import os
import matplotlib.pyplot as plt
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv
import numpy as np

# Setup
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Constants
EXCEL_PATH = 'es4c13900_si_001.xlsx'
JSON_PATH = '/home/chen/GNPS_SIM/agent/searching_results/run_20260218_193647/ner_results/chemical_ner_results.json'
OUTPUT_PLOT = 'dbp_coverage_plot_llm_enhanced.png'
OUTPUT_CSV = 'llm_normalization_mapping.csv'

class ChatOpenRouter(ChatOpenAI):
    def __init__(self, openai_api_key=None, **kwargs):
        super().__init__(base_url="https://openrouter.ai/api/v1", openai_api_key=openai_api_key, **kwargs)

def load_data():
    # 1. Load Excel DBPs (Reference)
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=1)
        if 'IUPAC name' not in df.columns:
             df = pd.read_excel(EXCEL_PATH, sheet_name='TableS1_716 Confirmed DBPs', header=0)
             if 'IUPAC name' in df.iloc[0].values:
                 df.columns = df.iloc[0]
                 df = df[1:]
        reference_dbps = df['IUPAC name'].dropna().astype(str).unique().tolist()
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return [], []

    # 2. Load Found Chemicals (NER Results)
    try:
        with open(JSON_PATH, 'r') as f:
            data = json.load(f)
        
        found_names = set()
        if 'per_file_results' in data:
            for file_res in data['per_file_results']:
                entities = file_res.get('entities', {})
                for entity_id, info in entities.items():
                    # Add mentions
                    for m in info.get('mentions', []):
                         if "(Context:" in m:
                             name = m.split("(Context:")[0].strip()
                         else:
                             name = m.strip()
                         if name: found_names.add(name)
                    # Add synonyms
                    for s in info.get('synonyms', []):
                        found_names.add(s)
    except Exception as e:
        print(f"Error reading JSON: {e}")
        return [], []
        
    return reference_dbps, list(found_names)

def find_matches(reference_dbps, found_names):
    # Normalize for exact match
    ref_norm = {r.lower().strip(): r for r in reference_dbps}
    found_norm = {f.lower().strip() for f in found_names}
    
    # 1. Exact Match
    matches = {}
    missing = []
    
    for r_lower, r_original in ref_norm.items():
        if r_lower in found_norm:
            matches[r_original] = {"match_type": "exact", "candidate": r_original, "score": 1.0}
        else:
            missing.append(r_original)
            
    print(f"Exact Matches: {len(matches)} / {len(reference_dbps)}")
    
    if not missing:
        return matches
        
    # 2. Semantic Retrieval (TF-IDF)
    print(f"Running Semantic Retrieval for {len(missing)} missing items against {len(found_names)} found names...")
    
    # Vectorize
    vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5)) # Character n-grams best for chemicals
    all_corpus = missing + found_names
    tfidf_matrix = vectorizer.fit_transform(all_corpus)
    
    missing_vecs = tfidf_matrix[:len(missing)]
    found_vecs = tfidf_matrix[len(missing):]
    
    # Cosine Similarity
    similarity_matrix = cosine_similarity(missing_vecs, found_vecs)
    
    # 3. LLM Setup
    llm = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0, openai_api_key=OPENROUTER_API_KEY)
    
    potential_matches = []
    
    for i, ref_dbp in enumerate(missing):
        # Get top 3 candidates
        top_indices = similarity_matrix[i].argsort()[-3:][::-1]
        candidates = []
        for idx in top_indices:
            score = similarity_matrix[i][idx]
            cand_name = found_names[idx]
            if score > 0.5: # Initial threshold
                candidates.append((cand_name, score))
        
        if candidates:
            potential_matches.append((ref_dbp, candidates))
            
    print(f"Reviewing {len(potential_matches)} potential matches with LLM...")
    
    llm_matches = 0
    
    # Batch processing could be faster, but let's loop for simplicity/robustness first
    for ref_dbp, candidates in potential_matches:
        # Construct prompt
        candidate_str = "\n".join([f"- {c[0]} (Similarity: {c[1]:.2f})" for c in candidates])
        curr_prompt = (
            f"Reference Chemical: '{ref_dbp}'\n"
            f"Found Candidates:\n{candidate_str}\n\n"
            "Task: Determine if any of the 'Found Candidates' are effectively the same chemical substance (synonym, isomer, or close spelling variant) as the 'Reference Chemical'.\n"
            "Ignore minor differences in capitalization or punctuation.\n"
            "If yes, return JSON: {\"match\": true, \"candidate\": \"<name>\"}\n"
            "If no, return JSON: {\"match\": false}\n"
            "Strict JSON only."
        )
        
        try:
            resp = llm.invoke([
                SystemMessage(content="You are a chemical entity resolution expert."),
                HumanMessage(content=curr_prompt)
            ])
            
            import re
            content = resp.content
            match = re.search(r'\{[\s\S]*\}', content)
            if match:
                res_json = json.loads(match.group(0))
                if res_json.get("match"):
                    matches[ref_dbp] = {
                        "match_type": "llm_verified",
                        "candidate": res_json.get("candidate"),
                        "score": 0.99 # Verified
                    }
                    llm_matches += 1
                    print(f"Matched: {ref_dbp} -> {res_json.get('candidate')}")
        except Exception as e:
            print(f"LLM Error on {ref_dbp}: {e}")
            
    print(f"LLM Verified Matches: {llm_matches}")
    return matches

def plot_results(total_refs, matches):
    found_count = len(matches)
    missing_count = total_refs - found_count
    
    labels = [f'Recovered ({found_count})', f'Not Found ({missing_count})']
    sizes = [found_count, missing_count]
    colors = ['#66b3ff', '#ff9999']
    explode = (0.1, 0)

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, text, autotext = ax.pie(sizes, explode=explode, labels=labels, colors=colors, 
                                    autopct='%1.1f%%', shadow=True, startangle=140,
                                    textprops=dict(color="black"))
    
    plt.setp(autotext, size=12, weight="bold")
    plt.setp(text, size=12)
    
    ax.axis('equal')  
    plt.title(f"Coverage of Reference DBPs (Total: {total_refs})\n(LLM-Enhanced Normalization)", fontsize=14)
    
    plt.savefig(OUTPUT_PLOT, dpi=300, bbox_inches='tight')
    print(f"Plot saved to {OUTPUT_PLOT}")
    
    # Save CSV
    pd.DataFrame([{ "Reference": k, "Type": v["match_type"], "Candidate": v["candidate"] } for k,v in matches.items()]).to_csv(OUTPUT_CSV, index=False)

if __name__ == "__main__":
    refs, found = load_data()
    if refs and found:
        print(f"Reference DBPs: {len(refs)}")
        print(f"Found Names: {len(found)}")
        matches = find_matches(refs, found)
        plot_results(len(refs), matches)
