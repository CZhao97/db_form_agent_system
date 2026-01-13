import sys
import os
import json
import tqdm

# Add code directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'code'))

from offline_paper_tool import OfflinePaperDumpTool

def dump_all_papers(output_file="all_papers.jsonl", index_path="./pmc_faiss_index"):
    tool = OfflinePaperDumpTool(index_path=index_path)
    
    # Get total count first
    initial_res = json.loads(tool.run({"limit": 1, "offset": 0}))
    total = initial_res.get("total", 0)
    print(f"Found {total} documents in index: {index_path}")
    
    batch_size = 100
    offset = 0
    
    with open(output_file, "w", encoding="utf-8") as f:
        pbar = tqdm.tqdm(total=total, desc="Dumping papers")
        
        while offset < total:
            # Fetch batch with full text
            res_json = tool.run({
                "limit": batch_size, 
                "offset": offset, 
                "full_text": True,
                "index_path": index_path
            })
            res = json.loads(res_json)
            
            docs = res.get("results", [])
            if not docs:
                break
                
            for doc in docs:
                # Write each document as a JSON line
                json.dump(doc, f)
                f.write("\n")
            
            count = len(docs)
            offset += count
            pbar.update(count)
            
    print(f"\nSuccessfully dumped {offset} documents to {output_file}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Dump all papers from FAISS index to JSONL")
    parser.add_argument("--output", default="all_papers.jsonl", help="Output file path")
    parser.add_argument("--index", default="./pmc_faiss_index", help="Path to FAISS index")
    
    args = parser.parse_args()
    dump_all_papers(args.output, args.index)
