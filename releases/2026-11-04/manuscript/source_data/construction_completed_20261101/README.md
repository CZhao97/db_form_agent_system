# Five-topic construction release

Each topic file contains 200 distinct retained entries. The combined file contains
1,000 rows. Every row has a Confirmed decision, an accepted release flag and
source-located attributed text for every paper citation. The release contains
7,689 paper citation instances. Database and tool records are excluded from that count.

## Columns and provenance

- `match_or_not`: 594 established benchmark matches and 406 without an established
  match. The latter include 54 identity-review cases and 22 unresolved lookups.
  See `overlap_status` and the detailed match evidence. Non-match does not establish absence.
- Identity matching preserves stereochemistry and isotopes and applies the
  approved acid/conjugate-base equivalence policy. Generated synonyms alone do
  not override known structure conflicts.
- `explanation`, `criteria_json`, `evidence_json`, `query` and the original record
  paths retain the complete scientific output. Resolved identity metadata and
  corrected export synonyms are separate from the unchanged originals.
- `assay_measurement_note` records the approved enzyme-hydrolysis context for
  rosmarinic acid. This is a total-parent-equivalent measurement, not free-parent
  detection in untreated plasma.
- Human annotation fields are blank for this release. Separate fixed expert
  review cohorts are not relabeled or transferred to these records.

The processed inventory contains 2,122 candidate records. Technical retries do
not add records. All failed attempts and reserved costs remain in the original
ledger. Detailed analysis inputs, raw results and checks are linked through
`RELEASE_SUMMARY.json` and the immutable manifests.
