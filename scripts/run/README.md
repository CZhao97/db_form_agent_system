# Pipeline Runners

This directory is reserved for public, machine-independent runner scripts.
The original experimental runners depended on local run folders and are not
included in the public snapshot.

Recommended workflow for a fresh public run:

1. Configure `.env` from `.env.example`.
2. Use the core modules in `code/` to refine a topic, retrieve literature,
   rank candidates, and verify candidate rows.
3. Store outputs under `local_runs/`, which is ignored by git.

The manuscript benchmark runs are reproduced from the external data package,
not from local machine-specific run folders.
