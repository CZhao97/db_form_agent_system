import lancedb
import matplotlib.pyplot as plt
import json
import pandas as pd
import pyarrow as pa
import time
import os

# 1. Connect to LanceDB
DB_PATH = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"
OUTPUT_PNG = "notebooks/ner_discovery_full.png"
OUTPUT_CSV = "notebooks/ner_discovery_full_data.csv"

def main():
    try:
        db = lancedb.connect(DB_PATH)
        tbl = db.open_table(TABLE_NAME)
        print(f"Connected to {DB_PATH}, Table: {TABLE_NAME}")
        total_rows = tbl.count_rows()
        print(f"Total Rows in DB: {total_rows}")
    except Exception as e:
        print(f"Connection Failed: {e}")
        return

    # 2. Stream Full Dataset
    BATCH_SIZE = 20000 # Increased batch size
    report_every = 1000000 # Report progress every 1M rows

    cumulative_counts = []
    doc_counts = []
    seen_chemicals = set()
    processed_count = 0
    ner_valid_count = 0
    start_time = time.time()

    print("Starting Full Scan...")
    
    # Select only ner_results column
    scanner = tbl.search().select(["ner_results"]).to_arrow()
    batches = scanner.to_batches(max_chunksize=BATCH_SIZE)
    
    for batch in batches:
        ner_strings = batch.column(0).to_pylist()
        
        for ner_str in ner_strings:
            processed_count += 1
            
            # Fast rejection
            if not ner_str or len(ner_str) <= 4:
                continue
            
            try:
                # Naive pre-check
                if ':' not in ner_str:
                    continue
                    
                data = json.loads(ner_str)
                if not isinstance(data, dict) or not data:
                    continue
                    
                ner_valid_count += 1
                seen_chemicals.update(data.keys())
                
                # Sampling for plot (save every 1000th valid doc)
                if ner_valid_count % 1000 == 0:
                    cumulative_counts.append(len(seen_chemicals))
                    doc_counts.append(ner_valid_count)
                    
            except Exception:
                continue
        
        if processed_count % report_every == 0:
            elapsed = time.time() - start_time
            rate = processed_count / elapsed if elapsed > 0 else 0
            print(f"Processed {processed_count} rows. Valid NER: {ner_valid_count}. Unique Chems: {len(seen_chemicals)}. Rate: {rate:.0f} rows/s")
            
            # Intermediate Save (Safety)
            if doc_counts:
                 pd.DataFrame({'valid_docs': doc_counts, 'unique_chemicals': cumulative_counts}).to_csv(OUTPUT_CSV, index=False)

    print(f"Finished Full Scan.")
    print(f"Total Rows: {processed_count}")
    print(f"Valid NER Docs: {ner_valid_count}")
    print(f"Total Unique Chemicals: {len(seen_chemicals)}")

    # 3. Plotting
    if cumulative_counts:
        plt.figure(figsize=(14, 7))
        plt.plot(doc_counts, cumulative_counts, color='darkgreen', linewidth=2, label='Cumulative Unique Chemicals')
        plt.xlabel("Valid Articles/Chunks Processed")
        plt.ylabel("Cumulative Count of Unique Chemicals")
        plt.title("Discovery Rate of Unique Chemicals (Full 266M Corpus Scan)")
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.legend()
        plt.tight_layout()
        plt.savefig(OUTPUT_PNG)
        print(f"Plot saved to {OUTPUT_PNG}")
        
        # Final CSV Save
        pd.DataFrame({'valid_docs': doc_counts, 'unique_chemicals': cumulative_counts}).to_csv(OUTPUT_CSV, index=False)
        print(f"Data saved to {OUTPUT_CSV}")
    else:
        print("No data to plot.")

if __name__ == "__main__":
    main()
