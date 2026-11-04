Current review interpretation (2026-11-03)

Botao Liu's four evaluation cohorts were reviewed with system decision labels
hidden, as confirmed in BLINDING_CLARIFICATION_20261026.json and reiterated by
the author. This is label-blinded review by a co-author, not a claim that the
reviewer was outside the author team or that explanations were hidden.
The author also confirmed that all rows were reviewed and that blank comments
represented agreement. Clarified comments and current cohort counts are reported
in main-text Methods and Supplementary Note 9.

The acquisition note below is preserved as a historical record. Its requests for
clarification predate the author confirmations and are not the current protocol.

Historical human-review evidence recovered on 2026-10-15

1. Explicit model-disagreement labels
Source: manuscript/human_evaluation/completed_pilot_annotations/
model_swap_disagreement_review_20260706/model_swap_disagreement_review_sheet_labeled.xlsx
The populated annotation column is "blind", not "human_preferred_label".
There are 13 explicit labels: 9 Confirmed, 2 Insufficient Direct Evidence,
2 Explicit Negative Evidence. Exact agreement: original 1/13, Gemini replay
7/13, neither 5/13. Binary agreement: original 3/13, Gemini replay 9/13.
These cases were selected for disagreement. Do not generalize these rates to
all outputs, rank models on them, or claim reviewer independence/blinding.
Botao attribution comes from the user's earlier identification of this file.

2. Historical 250-row construction review
Five db_curator_confirmed*BL* CSVs contain 50 rows each. See the file inventory.
Free-text notes include positive and negative judgments. Blank comments are not
explicit votes. The historical script generate_all_labeled_summaries.py used
blank = human OK and also misclassified some positive narrative comments as
flags. Its aggregate must not be quoted as expert accuracy without checking
the original review convention. These files do not validate the newer 1,000 rows.

3. Historical Critique-change correctness
section24_fig6b_change_correctness.csv has 54 rows, of which only 5 have a
nonblank manual_label. Its derived 49/49 rescued-correct count uses the
blank-comment convention and is not 49 explicit positive votes. Preserve it
as historical output, not a newly verified expert metric.

Next clarification: Did the reviewer inspect every row and deliberately leave
correct rows blank? If yes, document this review protocol and interpret the
actual notes one by one. Otherwise report explicit annotations only.

Expanded inventory:
- human_audit_labels_*BL: five zero-shot baseline files, 250 records, two
  nonblank inspection comments. The newer human_audit_label/notes columns are
  empty; automatic review flags are not human annotations.
- Five full-loop BL files: 1,887 stored records, 59 nonblank inspection notes
  (DBP 16, drug 11, endogenous 17, microbial 15, blood 0). Stored counts differ
  between blood (301) and endogenous (299) and need row-level reconciliation
  before linking to the current 300-per-topic benchmark cohorts.
- Blood non-Confirmed file: 14 records, two explicit comments.
- sec_1_result construction files are earlier versions, not an extra 250 cases.
- human_annotation workbooks contain 21 rows with explicit overlap/reference
  notes across 527 stored rows; authorship is not established by filenames.
- human_overlap_label workbooks contain mixed summary/recommendation sheets.
  Unrecognized columns mean unclassified, not unreviewed. These are identity
  reviews, not direct evidence-entailment adjudications.

historical_human_review_inventory.xlsx contains the expanded inventory and
verbatim annotations. Do not sum across historical versions or assume every
file in this inventory was authored by Botao without provenance confirmation.

audit.py reads originals without modifying them, recomputes the explicit
13-case labels and writes source hashes to summary.json. The reviewer response
draft now distinguishes these completed reviews from newer unfilled packages.
