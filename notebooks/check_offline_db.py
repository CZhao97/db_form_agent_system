
import lancedb
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def check_db(query_term):
    db_path = "/data/chen/GNPS_SIM/pmc_lancedb_index"
    try:
        db = lancedb.connect(db_path)
        if "papers_index" not in db.table_names():
            print("Table 'papers_index' NOT found in DB.")
            return
        
        tbl = db.open_table("papers_index")
        count = len(tbl)
        print(f"Total rows in DB: {count}")
        
        # Search
        print(f"Searching for: {query_term}")
        results = tbl.search(query_term).limit(50).to_pandas()
        
        print(f"Found {len(results)} raw matches.")
        
        hq_matches = 0
        if not results.empty and "_distance" in results.columns:
            hq_results = results[results["_distance"] < 0.75]
            hq_matches = len(hq_results)
            print(f"High Quality Matches (distance < 0.75): {hq_matches}")
        
        if not results.empty:
            print("Columns:", results.columns.tolist())
            cols_to_show = ['title', 'source', 'year']
            if '_distance' in results.columns:
                cols_to_show.append('_distance')
            print("Sample matches:")
            print(results[cols_to_show].head(10))
            print("\nSample text (first 200 chars):")
            print(results.iloc[0]['text'][:200])
        else:
            print("No matches found.")
            
    except Exception as e:
        print(f"Error: {e}")

import sys

if __name__ == "__main__":
    query = "chloral disinfection byproduct"
    if len(sys.argv) > 1:
        query = sys.argv[1]
    check_db(query)
