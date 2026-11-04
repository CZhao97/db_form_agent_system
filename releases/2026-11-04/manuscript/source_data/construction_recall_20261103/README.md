# Processed-Pool Recall After Author Clarification

The author confirmed on 2026-11-03 that all 95 non-Confirmed candidates outside
the blood topic had been reviewed by Botao and correctly remained non-Confirmed.
The author also explicitly classified 9-fluorenone and N-Acetylputrescine as
false negatives. These statements are preserved in `AUTHOR_CONFIRMATION.json`.
The other 12 blood candidates retain agreement under the previously confirmed
blank-comment convention. No missing annotation file is represented as recovered.

The retained-row labels use the clarified 2026-10-29 review: 241 qualifying
entries and nine objections among 250 retained entries. They do not reuse the
obsolete TP=246 count. The blank exported system label for benzalkonium chloride
is bound to its original native report by the exact saved query prefix and file
hash. That native report is Confirmed and accepted. This changes the available
Confirmed-label denominator from 249 to 250 without changing the expert judgment.

| Topic | TP | FP | FN | TN | Precision | Processed-pool recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DBP | 45 | 5 | 0 | 72 | 90.0% | 100.0% |
| Blood exposome | 50 | 0 | 2 | 12 | 100.0% | 96.2% |
| Drug | 50 | 0 | 0 | 1 | 100.0% | 100.0% |
| Endogenous metabolite | 47 | 3 | 0 | 15 | 94.0% | 100.0% |
| Microbial natural product | 49 | 1 | 0 | 7 | 98.0% | 100.0% |
| Total | 241 | 9 | 2 | 107 | 96.4% | 99.2% |

Precision = 241/(241+9) = 96.4%.
Processed-pool recall = 241/(241+2) = 99.17695%, rounded to 99.2%.

The evaluation unit is the reviewed construction record. The pool consists of
250 retained and 109 non-Confirmed records from the five 50-retained-per-topic
runs. It is not the later 1,000-entry release or all compounds in the literature.
Every reviewed retained row is linked to the original run directory, including
the recovered benzalkonium chloride record. No records cross between retained
and non-Confirmed groups.

## Files

- `construction_review_359_rows.csv`: per-row system decision, clarified human
  validity, confusion-matrix cell and source provenance.
- `processed_pool_precision_recall.csv`: topic-level and pooled metrics.
- `SUMMARY.json`: complete counts, input hashes and endpoint scope.
- `AUTHOR_CONFIRMATION.json`: the author's explicit clarification of the review.

Reproduce from the manuscript directory:

```bash
python3 -B reproduction/calculate_construction_recall.py
python3 -B -m unittest discover -s reproduction -p test_construction_recall.py -v
```

The original review files and historical recall generator remain unchanged.
This result supersedes the provisional statement that the non-Confirmed labels
could not yet be used for recall, based on the subsequent author clarification.
