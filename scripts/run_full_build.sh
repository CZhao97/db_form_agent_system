#!/bin/bash

# Set PyTorch memory configuration to reduce fragmentation
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Directory to clean
DB_DIR="/data/chen/GNPS_SIM/pmc_lancedb_index"

# Clean up existing database ONLY if requested (safety for resume)
if [ "$1" == "--clean" ]; then
    echo "WARNING: --clean flag used. This will delete the existing database and checkpoints."
    if [ -d "$DB_DIR" ]; then
        echo "Removing existing database at $DB_DIR..."
        rm -rf "$DB_DIR"
    fi
    # Also clean checkpoints
    rm -rf checkpoints/
fi

NUM_SHARDS=10
echo "Starting build process with $NUM_SHARDS shards on 2 GPUs..."

# Launch shards
for (( i=0; i<NUM_SHARDS; i++ ))
do
    # Distribute shards across 2 GPUs (even on GPU 0, odd on GPU 1)
    GPU_ID=$((i % 2))
    
    echo "Launching Shard $i on GPU $GPU_ID..."
    
    CUDA_VISIBLE_DEVICES=$GPU_ID python3 code/build_offline_db.py \
        --shard_id $i \
        --num_shards $NUM_SHARDS \
        --gpu_id 0 \
        --file_batch_size 200 \
        --ner_batch_size 128 \
        --linker_batch_size 16 > build_shard_$i.log 2>&1 &
        
    # Store PID
    pids[${i}]=$!
done

echo "All jobs started."
echo "Logs are being written to build_shard_*.log"
echo "You can monitor progress with: tail -f build_shard_0.log"
echo "Waiting for completion..."

# Wait for all PIDs
for pid in ${pids[*]}; do
    wait $pid
done


echo "Build complete!"
