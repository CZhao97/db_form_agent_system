
import lancedb
import pyarrow as pa

DB_PATH = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "pmc_articles" # Assuming table name, will check

try:
    db = lancedb.connect(DB_PATH)
    print(f"Connected to LanceDB at {DB_PATH}")
    print(f"Table names: {db.table_names()}")
    
    # Assuming 'pmc_articles' is the main table or 'ner_results'
    # List tables implies we get names
    tables = db.table_names()
    if not tables:
        print("No tables found!")
        exit()
        
    t_name = tables[0]
    tbl = db.open_table(t_name)
    print(f"Opened table: {t_name}")
    print(f"Schema: {tbl.schema}")
    print(f"Total rows: {tbl.count_rows()}")
    
    # Check for NER column
    # Use a small limit to peek
    df = tbl.search().limit(5).to_pandas()
    print("Columns:", df.columns.tolist())
    
    # Check row with NER
    # If there is a 'ner' or 'chemicals' column
    potential_cols = [c for c in df.columns if 'ner' in c.lower() or 'chem' in c.lower()]
    print(f"Potential NER columns: {potential_cols}")
    
    if potential_cols:
        col = potential_cols[0]
        # Count non-nulls if possible (might be slow on full DB, check small sample)
        # tbl.search().where(f"{col} IS NOT NULL").limit(5).to_pandas()
        print(f"Sample data in {col}:")
        print(df[col].head())

except Exception as e:
    print(f"Error: {e}")
