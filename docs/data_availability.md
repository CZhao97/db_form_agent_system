# Data Availability and External Artifacts

The public GitHub release intentionally excludes large and/or copyrighted runtime artifacts:

- downloaded PDFs and converted full text;
- cached paper assets;
- FAISS/vector indexes;
- SQLite/Parquet offline shards;
- full intermediate run logs;
- private local paths and machine-specific caches;
- virtual environments and package caches.

For full benchmark reproduction, pair this repository with the external data release described in the manuscript. The data release should contain:

- benchmark input tables for the five evaluation domains;
- DB-Curator output tables;
- zero-shot baseline outputs;
- human audit sheets;
- overlap annotations;
- citation-audit summaries;
- figure source tables.

If an artifact is too large for GitHub but required for a figure or table, place it in the external data package and reference it from the manifest rather than committing it to the repository.
