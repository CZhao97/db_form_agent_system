
"""
Script for Continuous Discovery with Live Metrics.
Runs the Upstream Agent in an infinite/long-running loop while a background thread
continuously monitors the NER output and calculates coverage against the Gold Standard.
"""
import os
import sys
import time
import threading
import logging
import json
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

# Add paths
sys.path.append(os.path.join(os.getcwd(), 'notebooks'))
sys.path.append(os.path.join(os.getcwd(), 'code'))

# MOCK SQLITE to bypass broken env (MUST BE BEFORE IMPORTS)
from unittest.mock import MagicMock
sys.modules["sqlite3"] = MagicMock()
sys.modules["sqlite3.dbapi2"] = MagicMock()

# Import Agent and Tools
from e2e_agent import upper_stream_agent_executor
from chemical_ner_tool import ChemicalNerTool

# Constants
EXCEL_PATH = 'es4c13900_si_001.xlsx'
MONITOR_INTERVAL_SECONDS = 120 # Run NER every 2 minutes

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [Continuous] - %(message)s')
logger = logging.getLogger(__name__)

class CoverageMonitor:
    def __init__(self, run_dir: str, excel_path: str):
        self.run_dir = run_dir
        self.excel_path = excel_path
        self.processed_files = set()
        self.found_dbps = set() # Set of normalized names
        self.stop_event = threading.Event()
        self.total_refs = 0
        self.ref_dbps_set = set() # Normalized reference Set
        self.lock = threading.Lock()
        
        # Initialize Reference Data
        self._load_references()
        
        # Initialize NER Tool
        self.ner_tool = ChemicalNerTool()

    def _load_references(self):
        try:
            # Try Header=1 first
            df = pd.read_excel(self.excel_path, sheet_name='TableS1_716 Confirmed DBPs', header=1)
            if 'IUPAC name' not in df.columns:
                 df = pd.read_excel(self.excel_path, sheet_name='TableS1_716 Confirmed DBPs', header=0)
                 if 'IUPAC name' in df.iloc[0].values:
                     df.columns = df.iloc[0]
                     df = df[1:]
            
            # Normalize references
            refs = df['IUPAC name'].dropna().astype(str).unique().tolist()
            self.ref_dbps_set = set(r.lower().strip() for r in refs)
            self.total_refs = len(self.ref_dbps_set)
            logger.info(f"Loaded {self.total_refs} Reference DBPs for tracking.")
            
        except Exception as e:
            logger.error(f"Failed to load Reference Excel: {e}")
            self.total_refs = 0

    def start(self):
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("CoverageMonitor thread started.")

    def stop(self):
        self.stop_event.set()
        logger.info("Stopping CoverageMonitor...")
        self.thread.join(timeout=5)

    def _monitor_loop(self):
        while not self.stop_event.is_set():
            try:
                self._run_incremental_update()
            except Exception as e:
                logger.error(f"Monitor Loop Error: {e}")
            
            # Sleep in small chunks to allow quick stop
            for _ in range(MONITOR_INTERVAL_SECONDS):
                if self.stop_event.is_set(): break
                time.sleep(1)

    def _run_incremental_update(self):
        if not os.path.exists(self.run_dir):
            logger.warning(f"Run dir {self.run_dir} does not exist yet.")
            return

        # 1. Identify New Files (Files that have not been NER'd)
        # We look for .json files that are NOT .ner_cache.json and NOT in processed_files
        all_json = [
            f for f in os.listdir(self.run_dir) 
            if f.endswith('.json') and not f.endswith('ner_cache.json') and not f.endswith('chemical_ner_results.json')
        ]
        
        new_files = [f for f in all_json if f not in self.processed_files]
        if not new_files:
            return # Nothing to do

        logger.info(f"Found {len(new_files)} new files to process.")
        
        # 2. Run NER on the Whole Folder (The tool handles caching efficiently)
        # We pass the FOLDER path. The tool will skip already cached files if logic permits,
        # or we just rely on its intrinsic speed.
        # Actually, to be safe and incremental, we rely on the tool's behavior.
        # The prompt says: "load_from_folder=true scans the folder... automatically extracts".
        
        try:
            # We call the tool programmatically
            # The tool returns a JSON string path
            result = self.ner_tool.run(
                texts=[self.run_dir],
                get_synonyms=False,
                load_from_folder=True
            )
            
            # 3. Parse the Results File
            # The tool writes to 'chemical_ner_results.json' in a 'ner_results' subdir or main dir depending on implementation
            # Let's verify output path from result
            if isinstance(result, str):
                try:
                    res_json = json.loads(result)
                    if isinstance(res_json, dict) and 'results_file' in res_json:
                        output_file = res_json['results_file']
                    else:
                        # Fallback guess
                        output_file = os.path.join(self.run_dir, "ner_results", "chemical_ner_results.json")
                except:
                     output_file = os.path.join(self.run_dir, "ner_results", "chemical_ner_results.json")
            
            if os.path.exists(output_file):
                self._update_stats(output_file)
                # Mark files as processed only after successful stats update
                self.processed_files.update(new_files)
                
        except Exception as e:
            logger.error(f"NER Execution Failed: {e}")

    def _update_stats(self, results_file: str):
        # Read the cumulative results file
        try:
            with open(results_file, 'r') as f:
                data = json.load(f)
            
            current_found = set()
            
            # Parse (Support both formats)
            if isinstance(data, dict) and 'per_file_results' in data:
                for file_res in data['per_file_results']:
                    entities = file_res.get('entities', {})
                    for info in entities.values():
                        for m in info.get('mentions', []):
                             name = m.split("(Context:")[0].strip() if "(Context:" in m else m.strip()
                             if name: current_found.add(name.lower())
                        for s in info.get('synonyms', []):
                            current_found.add(s.lower())
            
            # Calc Overlap
            with self.lock:
                self.found_dbps = current_found
                overlap = self.ref_dbps_set.intersection(self.found_dbps)
                count = len(overlap)
                ratio = (count / self.total_refs) * 100 if self.total_refs > 0 else 0
                
            # Log Metrics
            logger.info(f"--- LIVE METRICS ---")
            logger.info(f"Total Papers Processed: {len(self.processed_files)}")
            logger.info(f"Total Unique Entities: {len(self.found_dbps)}")
            logger.info(f"Gold Standard Coverage: {count}/{self.total_refs} ({ratio:.2f}%)")
            logger.info(f"--------------------")
            
        except Exception as e:
            logger.error(f"Stats Calculation Failed: {e}")

def main():
    # Setup Environment
    load_dotenv()
    os.environ["INCLUDE_OFFLINE_SEARCH"] = "True"
    os.environ["INCLUDE_S2"] = "True"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = "Agent Continuous Discovery"

    # Mocks moved to top of file

    # Create Run Directory
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.abspath(f"searching_results/run_continuous_{ts}")
    if not os.path.exists(run_dir):
        os.makedirs(run_dir)
    
    logger.info(f"Starting Continuous Run in: {run_dir}")

    # Start Monitor
    monitor = CoverageMonitor(run_dir, EXCEL_PATH)
    monitor.start()

    # Define Broad Query for Discovery
    # We use a broad prompt to encourage the agent to explore
    query = "Comprehensively identify all known and emerging disinfection byproducts (DBPs) formed in drinking water, including halogenated, nitrogenous, and carbonaceous species. Focus on finding novel compounds."
    
    state = {
        "messages": [HumanMessage(content=query)],
        "original_query": query,
        "search_session_dir": run_dir,
        "iteration_count": 0,
        "last_output": None
    }
    
    config = {"configurable": {"search_session_dir": run_dir, "thread_id": f"continuous_{ts}"}}
    
    try:
        logger.info("Invoking Agent Loop...")
        # The agent is technically finite (it has a stopping criteria), 
        # but the query is broad so it should run for a while.
        # If it stops, we can restart it with a new instruction or purely rely on its internal loop.
        # For this script, we assume the Agent's internal "Iterative" loop will run for multiple cycles.
        
        result = upper_stream_agent_executor.invoke(state, config=config)
        logger.info("Agent Finished Execution.")
        
    except KeyboardInterrupt:
        logger.info("User stopped execution.")
    except Exception as e:
        logger.error(f"Agent Failed: {e}")
    finally:
        monitor.stop()

if __name__ == "__main__":
    main()
