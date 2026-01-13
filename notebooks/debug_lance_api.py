
import lancedb
import sys

try:
    db = lancedb.connect('/data/chen/GNPS_SIM/pmc_lancedb_index')
    tbl = db.open_table('papers_index')
    methods = dir(tbl)
    
    with open('debug_api.txt', 'w') as f:
        f.write('\n'.join(methods))
    print("Methods written to debug_api.txt")
except Exception as e:
    print(f"Error: {e}")
