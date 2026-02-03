import json
import os
import random
import time
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.callbacks import get_openai_callback

# Constants
NER_RESULTS_PATH = 'agent/searching_results/e2e_run_20260125_130247/literature_searching/ner_results/chemical_ner_results.json'
SAMPLE_SIZE = 5
OUTPUT_CSV = 'ner_vs_llm_comparison.csv'

# Pricing (approximate, per 1K tokens)
# GPT-4o
PRICE_INPUT_GPT4O = 0.005 / 1000
PRICE_OUTPUT_GPT4O = 0.015 / 1000

def load_ner_results():
    with open(NER_RESULTS_PATH, 'r') as f:
        return json.load(f)

def get_paper_content(file_path):
    # The file paths in ner_results might be absolute or relative
    # If they are relative to the run dir, we might need to adjust.
    # Let's check if they exists.
    if not os.path.exists(file_path):
        # Try finding it relative to current dir or agent dir?
        # Based on previous ls, they are in 'agent/searching_results/...'
        # Let's assume the path in JSON is usable or we can fix it.
        pass
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            # Prefer full text, fallback to abstract
            text = data.get('full_text', '')
            if not text or len(text) < 50:
                text = data.get('abstract', '')
            return text
    except Exception as e:
        print(f"Error reading paper {file_path}: {e}")
        return None

def extract_with_llm(text):
    llm = ChatOpenAI(
        model="gpt-4o", 
        temperature=0,
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert chemist. Identify all specific chemical names, compounds, and drugs mentioned in the text. Return them as a JSON list of strings."),
        ("human", "{text}")
    ])
    
    chain = prompt | llm
    
    with get_openai_callback() as cb:
        start_time = time.time()
        try:
            # Truncate text if too long to avoid context limit (though 4o has 128k)
            # Just separate safety check
            if len(text) > 100000:
                text = text[:100000]
                
            response = chain.invoke({"text": text})
            content = response.content
            
            # Clean content to ensure JSON
            content = content.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "")
            
            try:
                chemicals = json.loads(content)
                if not isinstance(chemicals, list):
                    chemicals = []
            except:
                chemicals = []
                
        except Exception as e:
            print(f"LLM Error: {e}")
            chemicals = []
            
        duration = time.time() - start_time
        
        return {
            'chemicals': chemicals,
            'tokens_in': cb.prompt_tokens,
            'tokens_out': cb.completion_tokens,
            'cost': cb.total_cost,
            'duration': duration
        }

def main():
    print("Loading NER results...")
    ner_data = load_ner_results()
    
    if 'per_file_results' not in ner_data:
        print("Invalid NER results format.")
        return

    all_files = ner_data['per_file_results']
    
    # Filter for files that actually exist
    valid_files = []
    for item in all_files:
        fpath = item.get('file')
        if fpath and os.path.exists(fpath):
            valid_files.append(item)
    
    if not valid_files:
        print("No valid files found to sample.")
        return

    print(f"Found {len(valid_files)} valid files. Sampling {SAMPLE_SIZE}...")
    sample = random.sample(valid_files, min(SAMPLE_SIZE, len(valid_files)))
    
    results = []
    
    for item in sample:
        fpath = item['file']
        print(f"Processing {os.path.basename(fpath)}...")
        
        # 1. Get Text
        text = get_paper_content(fpath)
        if not text:
            print("  No text found.")
            continue
            
        print(f"  Text length: {len(text)} chars")
        
        # 2. Results from NER (already done)
        ner_entities = item.get('entities', {})
        ner_chemicals = set()
        for eid, info in ner_entities.items():
            for m in info.get('mentions', []):
                # Clean prompt
                clean_m = m.split("(Context:")[0].strip()
                ner_chemicals.add(clean_m.lower())
        
        print(f"  NER found: {len(ner_chemicals)} unique chemicals")
        
        # 3. Results from LLM
        print("  Running LLM extraction...")
        llm_res = extract_with_llm(text)
        llm_chemicals = set(c.lower() for c in llm_res['chemicals'])
        
        print(f"  LLM found: {len(llm_chemicals)} unique chemicals")
        print(f"  LLM Cost: ${llm_res['cost']:.4f}")
        
        # 4. Compare
        overlap = ner_chemicals.intersection(llm_chemicals)
        
        results.append({
            'file': os.path.basename(fpath),
            'text_length': len(text),
            'ner_count': len(ner_chemicals),
            'llm_count': len(llm_chemicals),
            'overlap_count': len(overlap),
            'ner_unique': len(ner_chemicals - llm_chemicals),
            'llm_unique': len(llm_chemicals - ner_chemicals),
            'llm_cost': llm_res['cost'],
            'llm_tokens': llm_res['tokens_in'] + llm_res['tokens_out'],
            'llm_duration': llm_res['duration']
        })

    # Save
    df = pd.DataFrame(results)
    df.to_csv(OUTPUT_CSV, index=False)
    
    print("\nComparison Results:")
    print(df[['file', 'ner_count', 'llm_count', 'llm_cost']].to_string())
    
    print(f"\nTotal Estimated Cost for processing {len(valid_files)} files with LLM:")
    avg_cost = df['llm_cost'].mean()
    print(f"${avg_cost * len(valid_files):.2f}")
    
    print(f"\nTotal Cost for NER:")
    print("$0.00 (Local Compute)")

if __name__ == "__main__":
    main()
