"""Bind resource measurements to the runs used in the current benchmark results."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[3]
REPAIR = PROJECT / 'deliverables/revision_execution_20261020'


def rows(path):
    with path.open(encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def main():
    registry = REPAIR / 'benchmark_reconciled_20261026/benchmark1887_reconciled.csv'
    audit = HERE.parent / 'source_data/benchmark1887_case_audit.csv'
    final = rows(registry)
    historical = {r['case_id']: r for r in rows(audit)}
    hashes, cached, output = {}, {}, []

    def record(path):
        key = str(path)
        if key not in hashes:
            hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes[key]

    record(registry)
    record(audit)
    for r in final:
        source_row = ''
        if r['designated_repair'] == 'True':
            path = REPAIR / 'repair_runs' / r['case_id'] / 'result.json'
            result = json.loads(path.read_text())
            assert result['case_id'] == r['case_id'] and result['topic'] == r['topic']
            assert result['status'] == 'completed'
            unknown_calls = result['usage'].get('unknown_calls', 0)
            tokens = result['usage']['total_tokens']
            duration = result.get('elapsed_seconds', '')
            basis = 'designated_run_accounted_usage'
        else:
            h = historical[r['case_id']]
            path = Path(h['source_csv'])
            if path not in cached:
                cached[path] = rows(path)
            source_row = int(h['source_data_row_1based'])
            result = cached[path][source_row - 1]
            assert result['results_dir'] == str(Path(r['final_record_path']).parent)
            tokens = float(result['tokens_used'])
            duration = float(result['duration_sec'])
            unknown_calls = 0
            basis = 'saved_run_metrics'
        assert tokens > 0 and int(tokens) == tokens
        assert duration == '' or float(duration) > 0
        output.append(dict(case_id=r['case_id'], topic=r['topic'], candidate=r['candidate'],
                           final_label=r['final_label'], tokens=int(tokens),
                           duration_sec=duration, resource_basis=basis,
                           resource_source=str(path), resource_source_sha256=record(path),
                           source_row_1based=source_row,
                           final_record_path=r['final_record_path'],
                           final_record_sha256=r['final_record_sha256'],
                           unknown_usage_calls=unknown_calls,
                           token_status='complete_recorded_usage' if not unknown_calls else 'partial_recorded_usage',
                           runtime_status='recorded' if duration != '' else 'not_recorded'))
    recovery_path = HERE / 'source_data/benchmark_usage_attempt_reconciliation.csv'
    if recovery_path.is_file():
        record(recovery_path)
        by_id = {r['case_id']: r for r in output}
        seen = set()
        for recovery in rows(recovery_path):
            if recovery['status'] != 'usage_recovered_from_exact_request_receipt':
                continue
            assert recovery['attempt_id'] not in seen
            seen.add(recovery['attempt_id'])
            receipts = json.loads(recovery['recovered_receipts'])
            assert receipts
            for receipt in receipts:
                assert record(Path(receipt['source'])) == receipt['source_sha256']
            row = by_id[recovery['case_id']]
            row['tokens'] += int(recovery['additional_observed_tokens'])
            row['unknown_usage_calls'] -= 1
            assert row['unknown_usage_calls'] >= 0
            row['token_status'] = 'complete_recorded_usage' if not row['unknown_usage_calls'] else 'partial_recorded_usage'
    assert len(output) == len({r['case_id'] for r in output}) == 1887
    assert sum(r['final_label'] == 'Confirmed' for r in output) == 676
    assert sum(r['runtime_status'] == 'recorded' for r in output) == 1881
    expected = {r['topic']: json.loads(r['final_label_counts'])
                for r in rows(HERE / 'source_data/benchmark_labels.csv')}
    for topic, counts in expected.items():
        assert Counter(r['final_label'] for r in output if r['topic'] == topic) == counts
    summary = {}
    for label in ['Confirmed', 'Other outcomes']:
        group = [r for r in output if (r['final_label'] == 'Confirmed') == (label == 'Confirmed')
                 and r['token_status'] == 'complete_recorded_usage']
        summary[label] = {'n': len(group), 'median_tokens': float(np.median([r['tokens'] for r in group]))}
    for topic in expected:
        group = [r for r in output if r['topic'] == topic and r['runtime_status'] == 'recorded']
        summary[topic] = {'runtime_n': len(group),
                          'median_minutes': float(np.median([float(r['duration_sec']) / 60 for r in group]))}
    dest = HERE / 'source_data/benchmark_operational_current.csv'
    with dest.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    manifest = {'records': len(output), 'runtime_records': 1881,
                'complete_token_records': sum(r['token_status'] == 'complete_recorded_usage' for r in output),
                'confirmed': 676, 'summary': summary, 'input_hashes': hashes,
                'output_sha256': hashlib.sha256(dest.read_bytes()).hexdigest(),
                'token_definition': 'Recorded run tokens; designated-run usage retains its accounted attempts.',
                'runtime_definition': 'Saved duration_sec or cumulative elapsed_seconds of the corresponding run.',
                'runtime_missing': [r['case_id'] for r in output if r['runtime_status'] != 'recorded'],
                'new_model_calls': 0}
    (HERE / 'source_data/benchmark_operational_current_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
