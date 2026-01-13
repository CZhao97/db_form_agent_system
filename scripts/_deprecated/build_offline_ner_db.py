import os
import sys
import json
import time
import argparse
import traceback
import threading
import queue
from pathlib import Path
from typing import List, Set
import torch.multiprocessing as mp
import torch # Added import

# Add the code directory to sys.path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "code"))

from chemical_ner_tool import extract_chemicals_with_nen_batch

def load_processed_files(log_path: Path) -> Set[str]:
    if not log_path.exists():
        return set()
    with open(log_path, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f)

def append_processed_files(log_path: Path, filenames: List[str]):
    with open(log_path, 'a', encoding='utf-8') as f:
        for name in filenames:
            f.write(f"{name}\n")

def save_batch_results(output_dir: Path, batch_results: List[dict], batch_index: int):
    timestamp = int(time.time())
    filename = f"ner_results_batch_{batch_index}_{timestamp}.json"
    output_path = output_dir / filename
    
    mention_count = 0
    for entry in batch_results:
        for kb_id, val in entry.get("entities", {}).items():
            mention_count += len(val.get("mentions", []))

    output_data = {
        "error": False,
        "results_file": str(output_path),
        "mention_count": mention_count,
        "merged_output": {}, 
        "per_file_results": batch_results
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"[Saver] Saved {len(batch_results)} files to {filename}")

def worker_process(gpu_id: int, input_queue: mp.Queue, output_queue: mp.Queue, batch_size: int, ner_batch_size: int, linker_batch_size: int):
    """
    Worker process that consumes batches of text and runs NER on a specific GPU.
    """
    print(f"[Worker {gpu_id}] Started on GPU {gpu_id}")
    
    while True:
        try:
            task = input_queue.get()
            if task is None:
                break
            
            batch_texts, batch_filenames = task
            
            try:
                # Run NER on the assigned GPU (both NER and Linker on same GPU)
                # Using larger mini-batches as optimized
                batch_results = extract_chemicals_with_nen_batch(
                    batch_texts,
                    ner_gpu=gpu_id,
                    linker_gpu=gpu_id,
                    use_fp16=True,
                    verbose=False,
                    ner_mini_batch_size=ner_batch_size,
                    linker_mini_batch_size=linker_batch_size,
                    max_chunk_chars=1500
                )
                
                processed_batch = []
                for i, res in enumerate(batch_results):
                    processed_batch.append({
                        "file": batch_filenames[i],
                        "entities": res
                    })
                
                output_queue.put(("result", processed_batch))
                
                # Clean up memory
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                
            except Exception as e:
                output_queue.put(("error", f"Worker {gpu_id} error: {str(e)}"))
                traceback.print_exc()
                
        except Exception as e:
            print(f"[Worker {gpu_id}] Critical error: {e}")
            break
            
    print(f"[Worker {gpu_id}] Finished")

def writer_thread_func(output_queue: mp.Queue, output_dir: Path, processed_log_path: Path, save_interval: int, initial_batch_index: int, stop_event: threading.Event):
    """
    Thread to handle saving results to disk.
    """
    results_buffer = []
    files_buffer = []
    batch_save_index = initial_batch_index
    total_saved = 0
    
    while not stop_event.is_set() or not output_queue.empty():
        try:
            msg = output_queue.get(timeout=0.5)
            if msg[0] == "result":
                batch_data = msg[1]
                for item in batch_data:
                    results_buffer.append(item)
                    files_buffer.append(item["file"])
                
                if len(results_buffer) >= save_interval:
                    save_batch_results(output_dir, results_buffer, batch_save_index)
                    append_processed_files(processed_log_path, files_buffer)
                    total_saved += len(results_buffer)
                    results_buffer = []
                    files_buffer = []
                    batch_save_index += 1
                    
            elif msg[0] == "error":
                print(f"[Writer] Received error: {msg[1]}")
                
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[Writer] Error: {e}")
            
    # Final save
    if results_buffer:
        save_batch_results(output_dir, results_buffer, batch_save_index)
        append_processed_files(processed_log_path, files_buffer)
        total_saved += len(results_buffer)
        
    print(f"[Writer] Finished. Total saved in this session: {total_saved}")

def read_and_enqueue(path, name, text_queue):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        if text.strip():
            text_queue.put((name, text))
    except Exception as e:
        print(f"[Reader] Error reading {name}: {e}")

def file_reader_thread(input_dir: Path, processed_files: Set[str], text_queue: queue.Queue, max_files: int):
    print(f"[Reader] Starting scan of {input_dir}...")
    import concurrent.futures
    
    max_pending = 1000
    pending_futures = set()
    count = 0
    
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            with os.scandir(input_dir) as it:
                for entry in it:
                    if entry.name.endswith('.txt') and entry.is_file() and entry.name not in processed_files:
                        
                        # Backpressure
                        while len(pending_futures) >= max_pending or text_queue.qsize() > 1000:
                            done = {f for f in pending_futures if f.done()}
                            pending_futures -= done
                            if len(pending_futures) >= max_pending or text_queue.qsize() > 1000:
                                time.sleep(0.01)
                        
                        fut = executor.submit(read_and_enqueue, entry.path, entry.name, text_queue)
                        pending_futures.add(fut)
                        
                        count += 1
                        if max_files > 0 and count >= max_files:
                            break
            
            # Wait for remaining
            concurrent.futures.wait(pending_futures)
                
    except Exception as e:
        print(f"[Reader] Critical Error: {e}")
    finally:
        text_queue.put(None)
        print(f"[Reader] Finished scanning. Submitted {count} files.")

def main():
    # Essential for CUDA multiprocessing
    mp.set_start_method('spawn', force=True)
    
    parser = argparse.ArgumentParser(description="Build offline NER database with multi-GPU support.")
    parser.add_argument("--input_dir", type=str, default="/data/chen/pubmed_corpus/pmc_extracted_text", help="Directory containing .txt files")
    parser.add_argument("--output_dir", type=str, default="searching_results/offline_ner_db", help="Directory to save results")
    parser.add_argument("--batch_size", type=int, default=100, help="Number of files per NER batch per worker")
    parser.add_argument("--ner_batch_size", type=int, default=256, help="Mini-batch size for NER model")
    parser.add_argument("--linker_batch_size", type=int, default=512, help="Mini-batch size for Linker model")
    parser.add_argument("--save_interval", type=int, default=1000, help="Number of files to accumulate before saving a JSON chunk")
    parser.add_argument("--max_files", type=int, default=0, help="Stop after processing this many files (0 for no limit)")
    parser.add_argument("--gpus", type=str, default="0,1", help="Comma-separated list of GPU IDs to use (e.g. '0,1')")
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    processed_log_path = output_dir / "processed_files.txt"
    processed_files = load_processed_files(processed_log_path)
    print(f"[Init] Found {len(processed_files)} already processed files.")
    
    # Determine next batch index
    batch_save_index = 0
    existing_jsons = list(output_dir.glob("ner_results_batch_*.json"))
    if existing_jsons:
        indices = []
        for p in existing_jsons:
            try:
                parts = p.name.split('_')
                if len(parts) >= 4:
                    indices.append(int(parts[3]))
            except:
                pass
        if indices:
            batch_save_index = max(indices) + 1
            
    gpu_ids = [int(x) for x in args.gpus.split(',')]
    num_workers = len(gpu_ids)
    print(f"[Init] Using {num_workers} workers on GPUs: {gpu_ids}")
    
    # Queues
    input_queue = mp.Queue(maxsize=num_workers * 4) # Buffer enough for workers to stay busy
    output_queue = mp.Queue()
    
    # Start Workers
    workers = []
    for gpu_id in gpu_ids:
        p = mp.Process(target=worker_process, args=(gpu_id, input_queue, output_queue, args.batch_size, args.ner_batch_size, args.linker_batch_size))
        p.start()
        workers.append(p)
        
    # Start Writer Thread
    stop_event = threading.Event()
    writer_thread = threading.Thread(
        target=writer_thread_func,
        args=(output_queue, output_dir, processed_log_path, args.save_interval, batch_save_index, stop_event)
    )
    writer_thread.start()
    
    # Start Reader Thread (Decoupled I/O)
    text_queue = queue.Queue(maxsize=2000)
    reader_thread = threading.Thread(
        target=file_reader_thread,
        args=(input_dir, processed_files, text_queue, args.max_files)
    )
    reader_thread.start()
    
    # Main Loop: Batcher
    total_queued = 0
    ner_text_batch = []
    ner_filename_batch = []
    
    print(f"[Init] Starting batcher loop...")
    
    try:
        while True:
            try:
                item = text_queue.get(timeout=1.0)
            except queue.Empty:
                if not reader_thread.is_alive():
                    break # Reader finished and queue empty
                continue
            
            if item is None:
                break
                
            fname, text = item
            ner_text_batch.append(text)
            ner_filename_batch.append(fname)
            
            if len(ner_text_batch) >= args.batch_size:
                input_queue.put((ner_text_batch, ner_filename_batch))
                total_queued += len(ner_text_batch)
                ner_text_batch = []
                ner_filename_batch = []
                
                if total_queued % 1000 == 0:
                    print(f"[Progress] Queued {total_queued} files...")
        
        # Remaining batch
        if ner_text_batch:
            input_queue.put((ner_text_batch, ner_filename_batch))
            total_queued += len(ner_text_batch)

    except KeyboardInterrupt:
        print("\n[Stop] Interrupted by user.")
    except Exception as e:
        print(f"[Fatal Error] {e}")
        traceback.print_exc()
    finally:
        print("[Main] Scanning finished. Stopping workers...")
        # Signal workers to stop
        for _ in workers:
            input_queue.put(None)
            
        for p in workers:
            p.join()
            
        print("[Main] Workers stopped. Stopping writer...")
        stop_event.set()
        writer_thread.join()
        print("[Main] Done.")

if __name__ == "__main__":
    main()
