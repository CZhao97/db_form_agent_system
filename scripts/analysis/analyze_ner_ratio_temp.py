
import json
import sys

def analyze_ner_ratio(results_file):
    try:
        with open(results_file, 'r') as f:
            data = json.load(f)
        
        # Check structure: 'per_file_results' holds details
        per_file = data.get('per_file_results', [])
        
        total_docs = len(per_file)
        docs_with_entities = 0
        total_mentions = 0
        
        for doc in per_file:
            entities = doc.get('entities', {})
            # Entities is dict of KB_ID -> details
            if entities:
                docs_with_entities += 1
                for k in entities:
                    total_mentions += len(entities[k].get('mentions', []))
                    
        ratio = (docs_with_entities / total_docs) * 100 if total_docs > 0 else 0
        
        print(f"Total Documents Processed: {total_docs}")
        print(f"Documents with Entities: {docs_with_entities}")
        print(f"Total Mentions Found: {total_mentions}")
        print(f"NER Yield Ratio: {ratio:.2f}%")
        
        # Additional insight: Check sources
        sources = {}
        for doc in per_file:
            src = doc.get('source', 'Unknown')
            if src not in sources: sources[src] = 0
            if doc.get('entities'):
                sources[src] += 1
                
        print("\nYield by Source (Docs with Entities):")
        for s, count in sources.items():
            print(f"- {s}: {count}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_ner_ratio.py <results_file>")
        sys.exit(1)
    analyze_ner_ratio(sys.argv[1])
