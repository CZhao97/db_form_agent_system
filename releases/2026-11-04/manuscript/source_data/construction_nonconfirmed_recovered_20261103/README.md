# Recovered Non-Confirmed Construction Pool

Subsequent author clarification on 2026-11-03 confirmed review of the other 95
records and identified the two blood cases as false negatives. The resulting
359-row confusion matrix and recall are in `../construction_recall_20261103/`.
The provenance flags below still distinguish located files from author-confirmed
judgments. They do not override the later clarification.

The complete five-topic pool was recovered from `/data/chen/db_curator_results/sec1/`.
It contains 109 unique candidate/run records, matching the non-Confirmed counts
in the historical 359-processed / 250-retained construction summary.
All records have `config_tag=section1`. They are not supplied-candidate benchmark
records and are not from the subsequent 1,000-row construction release.

| Topic | Non-Confirmed records | Annotated review export located |
| --- | ---: | ---: |
| DBP | 72 | 0 |
| Blood exposome | 14 | 14 |
| Drug compounds | 1 | 0 |
| Human endogenous metabolites | 15 | 0 |
| Microbial natural products | 7 | 0 |
| Total | 109 | 14 |

## Files

- `all_109_nonconfirmed_full_features.csv`: every original column, including
  explanations, criteria, evidence, and source-run paths, with review provenance.
- `all_109_nonconfirmed_index.csv`: compact case list and review-file status.
- `topic_summary.csv`: per-topic counts and original source paths.
- `PROVENANCE.json`: input hashes and exact-link policy.
- `build_recovered_pool.py`: deterministic collection script.

The 14 blood records were linked to the original reviewed CSV by exact topic and
run-directory path, with a candidate-name check. Twelve comments are blank under
the author's confirmed review convention. Two comments are preserved verbatim.
These comments do not themselves specify a positive human-validity label.

The other 95 records were recovered as original system outputs. Their files
contain neither manual-review columns nor populated ground-truth labels.
`reviewed_export_not_located` describes the current file search, not a conclusion
that the reviewer did not review them. No human labels were imputed, and no
recall estimate was changed.

The wider search covered project CSVs/workbooks, historical ZIP contents,
review inventories and relevant `/data/chen` result/archive directories.
Search inventories and diagnostics are retained at
`/data/chen/nonconfirmed_review_search_20261103/`.
