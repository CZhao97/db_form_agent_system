
import pandas as pd
import json
import os
import random

FILE_PATH = "notebooks/dbp_gemini_flash_2_5_results.xlsx"

try:
    if not os.path.exists(FILE_PATH):
        print(f"Error: {FILE_PATH} not found.")
        exit(1)

    df = pd.read_excel(FILE_PATH)
    
    if "IUPAC name" not in df.columns:
        print(f"Error: 'IUPAC name' column not found in {FILE_PATH}. Columns: {df.columns.tolist()}")
        exit(1)
        
    # Get unique names, drop NaNs
    names = df["IUPAC name"].dropna().unique().tolist()
    # Clean up whitespace
    names = [str(n).strip() for n in names if str(n).strip()]
    
    print(json.dumps(names))

except Exception as e:
    print(f"Error reading file: {e}")
