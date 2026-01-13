#!/bin/bash

INDEX_PID=$1
echo "Supervisor: Monitoring Indexing PID $INDEX_PID..."

# Wait for the indexing process to finish
tail --pid=$INDEX_PID -f /dev/null

echo "Supervisor: Indexing process finished."

# Check logs for success
if grep -q "SUCCESS" notebooks/nohup_fts_index.out; then
    echo "Supervisor: Index building SUCCESS detected. Starting Evaluation..."
    nohup python3 notebooks/evaluate_dbp_downstream_only.py --workers 6 > notebooks/nohup_eval_fts.out 2>&1 &
    EVAL_PID=$!
    echo "Supervisor: Evaluation started with PID $EVAL_PID. Logging to notebooks/nohup_eval_fts.out"
else
    echo "Supervisor: Index building FAILED or no success message found. Check notebooks/nohup_fts_index.out"
fi
