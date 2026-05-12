# Evaluation Plan Summary

DB-Curator was evaluated in two complementary settings:

1. **Fixed-cohort release audit.** Each topic produced a 50-row release cohort.
   Rows were accepted automatically when they overlapped a benchmark by normalized
   identity, and non-overlap rows were manually inspected for topic validity and
   evidence support.
2. **Benchmark-scale verification.** Candidate rows from five source databases
   were verified against the user-defined topic rubric. Confirmed rows were
   treated as database-ready positive entries. Suspected, Explicit Negative
   Evidence, and Insufficient Direct Evidence rows were treated as not confirmed
   for positive-entry yield analysis.

The five domains were:

- disinfection byproducts;
- human blood exposome chemicals;
- drug compounds;
- human endogenous metabolites;
- microbial natural products.

Citation audits were performed at the cited-paper level. A paper reference was
counted as content-supported when the recovered paper text contained the quoted
evidence span or equivalent local context supporting the same candidate-relevant
claim. Compound-database lookup pages were excluded from primary-paper citation
counts.

The full benchmark input tables, output tables, human audits, overlap annotations,
and citation-audit tables are external data artifacts rather than GitHub source
files. See `docs/data_availability.md`.
