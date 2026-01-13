
import multiprocessing as mp
import os
import torch
import time
import sys

def worker_func(duration=2):
    pid = os.getpid()
    n_gpus = torch.cuda.device_count()
    
    if n_gpus == 0:
        return f"PID {pid}: No GPUs found"

    # Mimic the logic in e2e_agent.py
    gpu_idx = pid % n_gpus
    try:
        torch.cuda.set_device(gpu_idx)
        current_device = torch.cuda.current_device()
        device_name = torch.cuda.get_device_name(current_device)
        
        # Allocate a small tensor to actually init the context
        x = torch.ones(100).cuda()
        
        return {
            "pid": pid,
            "target_gpu": gpu_idx,
            "actual_device": current_device,
            "device_name": device_name,
            "success": True
        }
    except Exception as e:
        return {
            "pid": pid,
            "error": str(e),
            "success": False
        }

def main():
    print(f"Parent PID: {os.getpid()}")
    if not torch.cuda.is_available():
        print("CUDA not available in parent.")
        return

    n_gpus = torch.cuda.device_count()
    print(f"Detected {n_gpus} GPUs.")
    
    # Force 'spawn' as used in the real app
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass

    num_workers = 8
    print(f"Spawning {num_workers} workers...")
    
    with mp.Pool(processes=num_workers) as pool:
        results = pool.map(worker_func, [1]*num_workers)
        
    print("\n--- RESULTS ---")
    gpu_counts = {}
    for res in results:
        if not isinstance(res, dict) or not res['success']:
            print(f"Worker failed: {res}")
            continue
            
        print(f"PID {res['pid']} -> Assigned: GPU {res['target_gpu']} | Actual: {res['actual_device']} ({res['device_name']})")
        
        g = res['actual_device']
        gpu_counts[g] = gpu_counts.get(g, 0) + 1

    print("\n--- DISTRIBUTION ---")
    for gpu, count in gpu_counts.items():
        print(f"GPU {gpu}: {count} workers")

if __name__ == "__main__":
    main()
