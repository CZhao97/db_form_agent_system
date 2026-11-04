"""Calculate processed-pool recall using the clarified human review, not comment presence."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'source_data'
OUT = DATA / 'construction_recall_20261103'
RAW = Path('/data/chen/db_curator_results/sec1')
TOPICS = ['dbp', 'blood_exposome', 'drug_compounds',
          'human_endogenous_metabolites', 'microbial_natural_products']
csv.field_size_limit(100_000_000)


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(topic, rows):
    counts = {cell: sum(r['confusion_cell'] == cell for r in rows)
              for cell in ['TP', 'FP', 'FN', 'TN']}
    return {'topic': topic, 'processed': len(rows),
            'retained': counts['TP'] + counts['FP'],
            'nonconfirmed': counts['FN'] + counts['TN'], **counts,
            'precision': counts['TP'] / (counts['TP'] + counts['FP']),
            'processed_pool_recall': counts['TP'] / (counts['TP'] + counts['FN'])}


def main():
    confirmation_path = OUT / 'AUTHOR_CONFIRMATION.json'
    confirmation = json.loads(confirmation_path.read_text())
    assert confirmation['other_95_reviewed_and_correctly_nonconfirmed'] is True
    assert confirmation['blood_two_are_false_negatives'] is True
    fn_names = set(confirmation['false_negative_candidates'])
    review_path = DATA / 'human_comment_recheck/human_review_overlay_20261029.csv'
    review = [r for r in read(review_path) if r['cohort'] == 'construction_250_labeled_version']
    recovery_path = DATA / 'solid_evidence_20261017/benzalkonium_recovery_evidence.json'
    recovery = json.loads(recovery_path.read_text())
    native_path = Path(recovery['native_path'])
    assert sha(native_path) == recovery['native_sha256']
    native = json.loads(native_path.read_text())
    assert native['claim'] == 'Confirmed' and native['accepted'] is True
    hashes = {str(p): sha(p) for p in [confirmation_path, review_path, recovery_path, native_path]}
    output = []
    for topic in TOPICS:
        retained_path = RAW / topic / 'db_curator_confirmed.csv'
        rejected_path = RAW / topic / 'db_curator_not_confirmed.csv'
        for p in [retained_path, rejected_path]:
            hashes[str(p)] = sha(p)
        retained = {r['results_dir'].rstrip('/'): r for r in read(retained_path)}
        assert len(retained) == 50
        seen = set()
        for r in [r for r in review if r['topic'] == topic]:
            run = r['original_output_path'].rstrip('/')
            recovered = not bool(run)
            if recovered:
                assert topic == 'blood_exposome' and r['candidate'] == 'benzalkonium chloride'
                run = str(native_path.parent)
                with Path(r['source_file']).open(encoding='cp1252', newline='') as handle:
                    archived = list(csv.DictReader(handle))[int(r['source_data_row_1based'])-1]
                assert archived['query'] and native['query'].startswith(archived['query'])
                hashes[r['source_file']] = sha(Path(r['source_file']))
            raw = retained[run]
            assert run not in seen
            if raw.get('config_tag'):
                assert raw['config_tag'] == 'section1'
            seen.add(run)
            assert r['review_20261029_agreement'] in ['True', 'False']
            valid = r['review_20261029_agreement'] == 'True'
            output.append({
                'topic': topic, 'candidate_name': r['candidate'],
                'system_retained': True, 'system_claim': 'Confirmed',
                'human_qualifies': valid, 'confusion_cell': 'TP' if valid else 'FP',
                'review_basis': 'clarified_20261029_construction_review',
                'review_source': str(review_path),
                'native_label_recovery_used': recovered,
                'raw_source': str(retained_path), 'results_dir': run,
            })
        assert seen == set(retained)
        for raw in read(rejected_path):
            assert raw['config_tag'] == 'section1' and raw['claim'] != 'Confirmed'
            valid = topic == 'blood_exposome' and raw['candidate_name'] in fn_names
            output.append({
                'topic': topic, 'candidate_name': raw['candidate_name'],
                'system_retained': False, 'system_claim': raw['claim'],
                'human_qualifies': valid, 'confusion_cell': 'FN' if valid else 'TN',
                'review_basis': 'author_clarified_existing_review_20261103',
                'review_source': str(confirmation_path), 'native_label_recovery_used': False,
                'raw_source': str(rejected_path), 'results_dir': raw['results_dir'].rstrip('/'),
            })
    assert len(output) == len({(r['topic'], r['results_dir']) for r in output}) == 359
    assert {r['candidate_name'] for r in output if r['confusion_cell'] == 'FN'} == fn_names
    summary = [summarize(t, [r for r in output if r['topic'] == t]) for t in TOPICS]
    overall = summarize('all', output)
    assert [overall[k] for k in ['TP', 'FP', 'FN', 'TN']] == [241, 9, 2, 107]
    write(OUT / 'construction_review_359_rows.csv', output)
    write(OUT / 'processed_pool_precision_recall.csv', summary + [overall])
    (OUT / 'SUMMARY.json').write_text(json.dumps({
        'endpoint': 'Retention in the reviewed 50-per-topic construction cohorts',
        'overall': overall, 'topic_results': summary,
        'author_confirmation': str(confirmation_path), 'inputs': hashes,
        'script_sha256': sha(Path(__file__)),
        'original_annotations_modified': False, 'new_model_calls': 0,
        'applies_to_current_1000_release': False,
        'applies_to_entire_open_literature': False,
    }, indent=2) + '\n')
    print(json.dumps(summary + [overall], indent=2))


if __name__ == '__main__':
    main()
