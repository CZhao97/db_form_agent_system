# Current benchmark results

## Unified experiment

- Benchmark inputs: **1,887**, all with paired token and runtime measurements.
- Researcher-Confirmed: **975**. Topic counts: DBP 330, blood exposome 68, drugs 213, endogenous metabolites 125, microbial natural products 239.
- Literature reference instances: **7,647**, excluding database and tool records.
- Real literature: **7,624 (99.7%)**. Incorrect references: **23**. No pending literature-existence labels.
- Source-located attributed texts: **7,246**.
- Confirmed predictions contain **4,169** literature references, including **3,964** with located attributed text.
- Incorrect references occur in **15 candidates**, including **14 Confirmed predictions**. These cases are listed in the source data.
- Median token use: Confirmed **118,650**, other outcomes **375,023**. Other outcomes account for **66.7%** of tokens.

All results are reported as one experiment, without separating execution batches. The 402 returned records are integrated by citation instance, not added again to an existing denominator. Their labels resolve literature existence, not quotation correspondence. Two real books/chapters are included and one compound-only record is excluded.

## Updated Files

- `DB_Curator_main.pdf` and `DB_Curator_SI.pdf`
- `source_data/benchmark_consolidated_20261104/`: unified decisions, resources and references
- `source_data/benchmark_consolidated_20261104/incorrect_reference_instances.csv`: 23 incorrect references
- `source_data/benchmark_consolidated_20261104/candidates_with_incorrect_references.csv`: 15 linked candidates
- `source_data/token_analysis_consolidated_20261104/`: token/review summaries
- `CURRENT_DELIVERY_VALIDATION_20261104.json`: compilation, figure, numeric and editorial checks

## Validation

All 1,887 current measurements have recorded token and runtime data. Citation-instance uniqueness and labels were checked offline. Endpoint checks and 33 figure tests passed. Both PDFs compiled without overfull boxes or missing references. Updated Figure 3 and the SI citation table were inspected visually. No new model calls were made during consolidation.

Historical results, raw returns and cumulative ledgers remain preserved. Public reviewer access to the code/data repository remains a separate submission task.
