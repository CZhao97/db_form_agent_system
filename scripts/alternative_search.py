import lancedb
import time
import argparse
import pandas as pd

DB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"

def main():
    parser = argparse.ArgumentParser(description="Alternative Search Tool (Vector + SQL Filter)")
    parser.add_argument("query", type=str, help="Search query string")
    parser.add_argument("--mode", type=str, choices=["vector", "sql", "meta", "hybrid"], default="vector", 
                        help="Search mode: 'vector' (semantic), 'sql' (slow exact text scan), 'meta' (filter by title), 'hybrid' (vector + sql)")
    parser.add_argument("--limit", type=int, default=5, help="Number of results")
    parser.add_argument("--show_ner", action="store_true", help="Display NER results for matches")
    args = parser.parse_args()

    print(f"Connecting to {DB_URI}...")
    db = lancedb.connect(DB_URI)
    if TABLE_NAME not in db.table_names():
        print("Table not found!")
        return
    tbl = db.open_table(TABLE_NAME)

    print(f"--- Running search: '{args.query}' (Mode: {args.mode}) ---")
    start = time.time()
    
    if args.mode == "vector":
        # Semantic Search (Uses the embedding model registered in the table)
        # This works EVEN IF FTS is missing.
        df = tbl.search(args.query).limit(args.limit).to_pandas()
        
    elif args.mode == "meta":
        # Metadata filtering (SQL-like) on Title
        # Much faster than full text scan
        # Note: LanceDB SQL where clause requires matching the schema
        # We use a simple LIKE clause
        df = tbl.search().where(f"title LIKE '%{args.query}%'").limit(args.limit).to_pandas()
        
    elif args.mode == "sql":
        # Full content scan (Slow!)
        # Equivalent to: SELECT * FROM table WHERE text LIKE '%query%'
        print("Warning: scanning 266M rows... this might take minutes.")
        df = tbl.search().where(f"text LIKE '%{args.query}%'").limit(args.limit).to_pandas()
        df["search_method"] = "keyword"

    elif args.mode == "hybrid":
        print("--- Mode: Hybrid (Vector + Keyword Scan) ---")
        print("1. Running Vector Search...")
        df_vec = tbl.search(args.query).limit(args.limit).to_pandas()
        df_vec["search_method"] = "vector"
        
        print("2. Running Keyword Scan (Warning: scanning 266M rows... this might take minutes)...")
        # Optimization: Scan mostly limiting to matches
        df_sql = tbl.search().where(f"text LIKE '%{args.query}%'").limit(args.limit).to_pandas()
        df_sql["search_method"] = "keyword"
        
        # Combine and deduplicate
        if df_vec.empty and df_sql.empty:
            df = pd.DataFrame()
        else:
            # Concatenate
            df = pd.concat([df_vec, df_sql], ignore_index=True)
            # Deduplicate by doc_id, keeping the first (prioritize vector usually, or merge info?)
            # Let's keep vector ranking if present, but note method
            # We aggregate 'search_method' to show if found by both
            
            # Group by doc_id to merge methods
            def merge_methods(series):
                methods = sorted(list(set(series)))
                return "+".join(methods)
            
            df_dedup = df.groupby("doc_id", as_index=False).first() # Keep first row data
            # Update method column
            methods = df.groupby("doc_id")["search_method"].apply(merge_methods).reset_index()
            
            df = pd.merge(df_dedup.drop(columns=["search_method"]), methods, on="doc_id")
            
    end = time.time()
    
    if df.empty:
        print("No results found.")
    else:
        print(f"Found {len(df)} results in {end-start:.2f}s:")
        for idx, row in df.iterrows():
            method = row.get('search_method', 'unknown')
            print(f"[{idx+1}] {row.get('title', 'No Title')} ({row.get('year', 'N/A')}) [Found by: {method}]")
            print(f"    ID: {row.get('doc_id')}")
            # print(f"    Excerpt: {str(row.get('text'))[:200]}...")
            if args.show_ner:
                ner = row.get('ner_results')
                print(f"    NER: {str(ner)[:200]}...")
            print("-" * 40)

if __name__ == "__main__":
    main()
