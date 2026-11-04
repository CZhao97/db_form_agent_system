"""Recalculate the current benchmark citation and measurement totals offline."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'source_data/benchmark_consolidated_20261104'


def read(name):
    with (DATA / name).open(encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def main():
    summary = json.loads((DATA / 'SUMMARY.json').read_text())
    candidates = read('benchmark_all1887.csv')
    assert len(candidates) == len({r['case_id'] for r in candidates}) == 1887
    assert sum(r['researcher_label'] == 'Confirmed' for r in candidates) == 975
    measurements = read('benchmark_operational_current.csv')
    assert len(measurements) == 1887
    assert all(r['token_status'] == 'complete_recorded_usage' and r['runtime_status'] == 'recorded' for r in measurements)
    refs = [r for r in read('all_reference_instances.csv') if r['excluded_database_or_tool'] == 'False']
    assert len(refs) == 7647
    assert len({(r['case_id'], r['reference_index']) for r in refs}) == len(refs)
    assert sum(r['literature_existence'] == 'TRUE' for r in refs) == 7624
    assert sum(r['literature_existence'] == 'FALSE' for r in refs) == 23
    assert sum(r['source_and_attributed_text_verified'] == 'True' for r in refs) == 7246
    assert all(r['literature_existence'] in ('TRUE', 'FALSE') for r in refs)
    returned = read('citation_review_402_label.csv')
    assert len(returned) == 402
    assert all(not r['reviewer_quote_found'] for r in returned)
    assert summary['quote_checks_not_upgraded_by_existence'] is True
    print('PASS: 1,887 paired measurements, 975 Confirmed, 7,624/7,647 real references, 7,246 located texts.')


if __name__ == '__main__':
    main()
