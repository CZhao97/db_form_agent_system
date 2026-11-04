# Final Researcher endpoint sensitivity

Date: 2026-11-02. Offline analysis only. No paid calls, manuscript edits, or changes to official results.

## Question and endpoint

Keep the current designated runs, including Critique-triggered retrieval, unchanged. Replace the reported final decision with the last Researcher claim from the same run. A positive is `researcher_claim == Confirmed`, irrespective of approval or downstream release eligibility.

This is NOT a Researcher-only experiment. It also differs from removing only the approval requirement while retaining every identity, criterion, citation and release check. The latter would require replaying that modified contract and has not been computed here.

## Benchmark evaluation

| Topic | Candidates | Current final Confirmed | Last Researcher Confirmed | Difference |
|---|---:|---:|---:|---:|
| DBP | 687 | 246 | 329 | +83 |
| Blood exposome | 300 | 53 | 69 | +16 |
| Drugs | 300 | 141 | 214 | +73 |
| Endogenous metabolites | 300 | 76 | 126 | +50 |
| Microbial natural products | 300 | 160 | 238 | +78 |
| Total | 1,887 | 676 | 976 | +300 |

Confirmed yield becomes 51.7%, compared with 35.8%. These are system labels, not a new accuracy estimate.

All 300 added positives come from the current designated repaired records. Their current final labels are Insufficient Direct Evidence (200) or Suspected (100). Critique requested clarification for 216 and approved 84. Thus, the difference is not solely an approval veto. Release-check reasons include pending source audit and unresolved contract items as well as non-Confirmed final decisions. These fields can reflect early exits and are not an exhaustive causal classification of every failed condition.

The result is 976, not the historical 1,015. Historical labels are used only for the 1,306 unchanged records. Each of the 581 designated repairs uses its current, hash-verified canonical record and its own `researcher_claim`.

### Citation consequences

This regrouping uses the existing final evidence inventory and its latest source-check results. It does not rejudge whether a passage entails a criterion.

| Positive cohort | Rows | Paper citation instances | Source-checked instances | Rows with all paper instances checked |
|---|---:|---:|---:|---:|
| Current final | 676 | 2,615 | 2,615 | 676 |
| Last Researcher | 976 | 4,183 | 4,003 | 859 |
| Added positives only | 300 | 1,568 | 1,388 | 183 |

Under the Researcher endpoint, 180 citation instances remain unverified in the current inventory. One of the 976 rows has no counted primary-paper citation instance. Lack of verification is not a finding of fabrication. The whole-cohort citation inventory and source-check totals do not change, but the positive-cohort denominator does.

## Open-ended construction

There are 2,122 processed occurrences, including 29 technical non-completions. All 2,093 scientific outcomes have an explicit last Researcher label available in the saved records.

| Topic | Processed | Current saved Confirmed labels | Last Researcher Confirmed labels |
|---|---:|---:|---:|
| DBP | 707 | 223 | 269 |
| Blood exposome | 321 | 217 | 248 |
| Drugs | 331 | 206 | 238 |
| Endogenous metabolites | 360 | 216 | 281 |
| Microbial natural products | 403 | 210 | 248 |
| Total | 2,122 | 1,072 | 1,284 |

The current released set is 1,000 rows, not 1,072. Saved Confirmed labels and released unique compounds are different quantities. The Researcher endpoint adds 213 positive labels and removes one, for a net increase of 212 relative to the 1,072 saved positives.

Of the currently retained 1,000 rows, 999 have a Confirmed last Researcher claim. The exception is malondialdehyde: its archived Researcher claim is Suspected, while Critique approves Confirmed. Strictly switching to the Researcher claim would remove that row from the positive set.

The other 285 Researcher-positive occurrences are not automatically 285 additional releasable compounds. The current release also applies identity, class-level, duplicate and source checks. A new 200-per-topic release would require reselecting eligible identities and recomputing overlap and accumulation endpoints. This audit has not done that reselection.

Source binding: the `source_row` field for the 743 historical nonretained construction occurrences includes the CSV header. The script uses index `source_row - 2` and checks the candidate name for all 743. It never transfers a neighboring row's claim. Saved wrapper records are resolved to the repaired report when present, otherwise to the archived historical report.

## Repeats, ablations and model swap

- Primary Full configuration: 673/1,500 remains 673/1,500. There are seven nonpositive category changes, but no Confirmed/non-Confirmed changes. Binary repeat stability therefore does not change. The current 673 already include 37 Researcher-Confirmed reports with `accepted=False`.
- Zero-shot, frozen retrieval and the pre-Critique adaptive endpoint are not changed by replacing the final Full endpoint. Their current totals remain 317, 488 and 648, respectively.
- Gemini-Critique configuration: 673/1,500 becomes 647/1,500. Twenty-six current Confirmed decisions have a non-Confirmed Researcher claim. Archived reports show that Critique can promote, as well as withhold, confirmation.
- Cross-configuration binary agreement changes from 1,298/1,500 (86.5%) to 1,302/1,500 (86.8%). The equal final totals of 673 versus 673 would become 673 versus 647.

The old statement of equal final yields across Critique configurations would therefore need revision if this endpoint were adopted.

## Same-state feedback comparison

| Arm | Assigned | Completed | Last Researcher Confirmed | Accepted |
|---|---:|---:|---:|---:|
| A: criterion-directed | 100 | 98 | 58 | 42 |
| B: general review, same rubric | 100 | 99 | 48 | 36 |
| C: general review, explicit rubric withheld | 100 | 100 | 51 | 34 |

The manuscript's Confirmed counts in this experiment already use the last Researcher label. They do not change. Non-completed branches are not promoted using an intermediate saved label.

## What else changes

- Recorded total token use, runtime, requests and costs do not change. The same calls were executed.
- Grouping these resources by Confirmed versus other outcomes does change. `benchmark_resource_regrouping.csv` contains both groupings, using complete recorded token usage and available runtime.
- Criterion pass-rate comparisons grouped by final outcome would need to be replotted. Their underlying criterion states would not change.
- Human annotations remain attached to the exact outputs that were reviewed. An endpoint switch does not create expert validation for the newly positive repaired outputs. Any revised human-system agreement needs the corresponding reviewed-output linkage.
- Benchmark membership labels themselves do not change. A reselected construction release would have a different composition, so its overlap ratio cannot simply be inherited from the current 1,000 rows.

## Interpretation

The current experiments use different decision endpoints. A uniform last-Researcher label would make the prediction endpoint explicit, but it must be adopted consistently, including where it lowers Confirmed counts. Keep `researcher_label`, `critique_decision`, `accepted` and `release_eligible` as distinct fields. One can report a model's prediction without calling every positive prediction a released database row.

## Reproduction

Run from the project root:

```bash
/usr/bin/python3 -B deliverables/researcher_endpoint_sensitivity_20261102/analyze.py
```

`SUMMARY.json` contains the summaries. CSVs preserve per-record comparisons and sources. `INPUT_SHA256.json` records the inputs read during the calculation. No source labels, historical outcomes or manuscript files are overwritten.
