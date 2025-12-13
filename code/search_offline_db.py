import os
import sys
import lancedb
import json
from lancedb.rerankers import RRFReranker

# --- Configuration ---
# Must match the URI used in build_offline_db.py
LANCEDB_URI = os.path.abspath("./pmc_lancedb_index")
TABLE_NAME = "papers_index"

def main():
    # Check if database exists
    if not os.path.exists(LANCEDB_URI):
        print(f"Error: Database not found at {LANCEDB_URI}")
        print("Please run build_offline_db.py first to create the index.")
        return

    print(f"Connecting to LanceDB at {LANCEDB_URI}...")
    try:
        db = lancedb.connect(LANCEDB_URI)
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return

    if TABLE_NAME not in db.table_names():
        print(f"Error: Table '{TABLE_NAME}' not found in database.")
        print(f"Available tables: {db.table_names()}")
        return

    # Open the table
    tbl = db.open_table(TABLE_NAME)
    
    # Initialize reranker
    reranker = RRFReranker()

    print("\n=== Offline Paper Search & Retrieval ===")
    print(f"Loaded index with {tbl.count_rows()} chunks.")
    print("Type a query to search. Type 'exit' to quit.")
    
    while True:
        try:
            query = input("\nQuery: ").strip()
            if query.lower() in ('exit', 'quit'):
                break
            if not query:
                continue
                
            print(f"Searching for: '{query}'...")
            
            # Perform Hybrid Search
            # Note: The embedding function is serialized with the table, 
            # so we can pass the text query directly.
            results = (
                tbl.search(query, query_type="hybrid")
                .rerank(reranker)
                .limit(3)
                .to_pandas()
            )
            
            if results.empty:
                print("No results found.")
                continue

            for i, row in results.iterrows():
                doc_id = row['doc_id']
                score = row['_relevance_score']
                title = row['title']
                chunk_text = row['text']
                ner_json = row['ner_results']
                
                print(f"\n--- Result {i+1} (Score: {score:.4f}) ---")
                print(f"ID: {doc_id}")
                print(f"Title: {title}")
                print(f"Snippet: {chunk_text[:200]}...")
                
                # Parse and display NER results
                try:
                    ner_data = json.loads(ner_json)
                    if ner_data:
                        print("NER Entities Found:")
                        # Display first few entities as a preview
                        count = 0
                        for mesh_id, details in ner_data.items():
                            mentions = details.get('mentions', [])
                            # Flatten mentions if they are in the structure [{"text": [...]}]
                            flat_mentions = []
                            for m in mentions:
                                if isinstance(m, dict) and 'text' in m:
                                    flat_mentions.extend(m['text'])
                                elif isinstance(m, str):
                                    flat_mentions.append(m)
                            
                            print(f"  - {mesh_id}: {flat_mentions[:3]} ...")
                            count += 1
                            if count >= 3:
                                print("  ... (more entities hidden)")
                                break
                    else:
                        print("NER: No entities in this document.")
                except json.JSONDecodeError:
                    print("NER: Error parsing stored JSON.")
                
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"An error occurred during search: {e}")

if __name__ == "__main__":
    main()
