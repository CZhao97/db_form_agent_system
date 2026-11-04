import csv
import json
from pathlib import Path
from calculate_construction_recall import summarize
root = Path(__file__).resolve().parents[1] / 'source_data/construction_recall_20261103'
with (root / 'construction_review_359_rows.csv').open(encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))
r = summarize('all', rows)
assert [r[k] for k in ['TP','FP','FN','TN']] == [241,9,2,107]
assert len(rows) == 359
print(json.dumps(r, indent=2))
