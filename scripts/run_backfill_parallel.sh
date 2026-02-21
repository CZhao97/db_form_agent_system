#!/bin/bash

# Configuration
NUM_SHARDS=10
BATCH_SIZE=64

# Set PyTorch memory configuration
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

echo "Starting backfill process with $NUM_SHARDS shards..."

for (( i=0; i<NUM_SHARDS; i++ ))
do
    # Round-robin GPUs (0, 1)
    GPU_ID=$((i % 2))
    
    echo "Launching Backfill Shard $i on GPU $GPU_ID..."
    
    nohup python notebooks/backfill_ner.py \
        --shard_id $i \
        --num_shards $NUM_SHARDS \
        --gpu_id $GPU_ID \
        --batch_size $BATCH_SIZE \
        > backfill_shard_$i.log 2>&1 &
        
    pids[${i}]=$!
    echo "  -> Started PID ${pids[${i}]}"
done

echo "All backfill shards started."
echo "Monitor with: tail -f backfill_shard_0.log"
