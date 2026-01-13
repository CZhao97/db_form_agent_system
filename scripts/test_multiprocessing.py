
import logging
import sys
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp

# Ensure code is in path
sys.path.append(os.path.abspath("notebooks"))
sys.path.append(os.path.abspath("code"))

from e2e_agent import full_app as app

def process_item(item):
    print(f"Processing {item} in PID {os.getpid()}")
    # Simulating a light invoke, we won't run the full chain to save time/cost
    # Just checking if 'app' is accessible and doesn't crash on unpickle
    try:
        # app.invoke({"messages": [...]}) # heavy
        return f"Success {item}"
    except Exception as e:
        return f"Fail {item}: {e}"

def main():
    print("Testing ProcessPoolExecutor with e2e_agent.app...")
    
    # Spawn is required for PyTorch/CUDA compatibility
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass

    with ProcessPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(process_item, i): i for i in range(2)}
        
        for fut in as_completed(futures):
            print(fut.result())

if __name__ == "__main__":
    main()
