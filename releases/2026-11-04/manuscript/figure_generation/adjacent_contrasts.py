"""Recompute adjacent-stage contrasts from frozen candidate-by-repeat labels."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'source_data'
TOPICS = ['dbp', 'blood_exposome', 'drug_compounds',
          'human_endogenous_metabolites', 'microbial_natural_products']
ARMS = ['zero_shot', 'static_rag', 'dynamic_retrieval_only', 'full_dbcurator']
CONTRASTS = [('Static-Zero', 1, 0), ('Dynamic-Static', 2, 1),
             ('Full-Dynamic', 3, 2), ('Full-Static', 3, 1)]
NBOOT = 20000


def read(path):
    with path.open(encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def bootstrap(groups, seed):
    # Keep the three repeats and all arms together within a candidate cluster.
    rng = np.random.default_rng(seed)
    result = np.zeros((NBOOT, len(CONTRASTS)))
    for group in groups:
        for start in range(0, NBOOT, 250):
            stop = min(start + 250, NBOOT)
            indices = rng.integers(0, len(group), size=(stop - start, len(group)))
            result[start:stop] += group[indices].sum(axis=1)
    return result / sum(len(group) for group in groups)


def compute(verify_existing=False):
    clusters_path = DATA / 'repeated500_candidate_clusters.csv'
    raw_path = ROOT.parent / 'source_data/solid_evidence_20261017/table_inputs/ablation_labels6000.csv'
    clusters, raw = read(clusters_path), read(raw_path)
    assert len(clusters) == 500 and len(raw) == 6000
    identity = lambda s: ' '.join(s.split()).casefold()
    raw_index = {(r['topic'], identity(r['candidate']), int(r['repeat']), r['group']): r for r in raw}
    assert len(raw_index) == 6000
    groups, counts = [], []
    for topic in TOPICS:
        rows = sorted((r for r in clusters if r['topic'] == topic), key=lambda r: int(r['topic_row_id']))
        assert len(rows) == 100
        matrices = []
        for row in rows:
            cube = np.array([[int(row[f'repeat{repeat}_{arm}_claim'] == 'Confirmed')
                              for arm in ARMS] for repeat in (2, 3, 4)])
            for j, arm in enumerate(ARMS):
                assert int(cube[:, j].sum()) == int(row[arm + '_confirmed_count'])
                for repeat in (2, 3, 4):
                    record = raw_index[topic, identity(row['compound']), repeat, arm]
                    assert record['claim'] == row[f'repeat{repeat}_{arm}_claim']
                    assert (record['confirmed'] == 'True') == (record['claim'] == 'Confirmed')
            matrices.append(cube)
        matrices = np.array(matrices)
        means = matrices.mean(axis=1)
        counts.append(matrices.sum(axis=(0, 1)))
        groups.append(np.column_stack([means[:, a] - means[:, b] for _, a, b in CONTRASTS]))
    assert np.array(counts).sum(axis=0).tolist() == [
        sum(r['claim'] == 'Confirmed' for r in raw if r['group'] == arm) for arm in ARMS]
    legacy = ({(r['topic'], r['contrast']): r for r in read(DATA / 'repeated_contrasts.csv')}
              if verify_existing else {})
    results = []
    for index, topic in enumerate(['all'] + TOPICS):
        selected = groups if topic == 'all' else [groups[index - 1]]
        total = np.array(counts).sum(axis=0) if topic == 'all' else counts[index - 1]
        n = 500 if topic == 'all' else 100
        seed = 20261110 + index
        distribution = bootstrap(selected, seed)
        for j, (name, a, b) in enumerate(CONTRASTS):
            lo, hi = np.quantile(distribution[:, j], [.025, .975], method='linear') * 100
            row = dict(topic=topic, contrast=name, candidate_clusters=n, repeats_per_cluster=3,
                       observations_per_arm=n * 3, a_confirmed=int(total[a]), b_confirmed=int(total[b]),
                       difference_pp=100 * (int(total[a]) - int(total[b])) / (n * 3),
                       ci95_low_pp=float(lo), ci95_high_pp=float(hi), seed=seed,
                       bootstrap_replicates=NBOOT)
            if (topic, name) in legacy:
                for key in ('difference_pp', 'ci95_low_pp', 'ci95_high_pp'):
                    assert abs(row[key] - float(legacy[topic, name][key])) < 1e-9, (topic, name, key)
            if name != 'Full-Static':
                results.append(row)
    return results, [clusters_path, raw_path] + ([DATA / 'repeated_contrasts.csv'] if verify_existing else [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-existing', action='store_true',
                        help='Also check previously exported contrasts when their labels are unchanged.')
    args = parser.parse_args()
    rows, inputs = compute(verify_existing=args.verify_existing)
    out = DATA / 'adjacent_stage_contrasts.csv'
    with out.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {'input_sha256': {str(p.relative_to(ROOT.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in inputs},
                'numpy_version': np.__version__, 'rng': 'PCG64', 'bootstrap_replicates': NBOOT,
                'existing_contrasts_checked': args.verify_existing, 'raw_labels_verified': 6000,
                'new_contrasts': 'Adaptive minus frozen, calculated from paired candidate clusters',
                'output_sha256': hashlib.sha256(out.read_bytes()).hexdigest(), 'new_model_calls': 0}
    (DATA / 'adjacent_stage_contrasts_metadata.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for row in rows:
        if row['contrast'] == 'Dynamic-Static':
            print(row['topic'], row['difference_pp'], row['ci95_low_pp'], row['ci95_high_pp'])


if __name__ == '__main__':
    main()
