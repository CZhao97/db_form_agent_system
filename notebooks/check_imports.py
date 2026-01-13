
import sys
import os

sys.path.append("/home/chen/GNPS_SIM/agent/db_form_agent_system/code")

print("Checking imports...")
try:
    from build_offline_db import PaperChunk
    print("SUCCESS: PaperChunk imported.")
except ImportError as e:
    print(f"FAILURE: PaperChunk import failed: {e}")
except Exception as e:
    print(f"FAILURE: PaperChunk import error: {e}")

try:
    from chemical_ner_tool import extract_chemicals_with_nen_batch
    print("SUCCESS: NER tool imported.")
except ImportError as e:
    print(f"FAILURE: NER tool import failed: {e}")
except Exception as e:
    print(f"FAILURE: NER tool import error: {e}")
