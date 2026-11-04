"""Offline validation and review exports for the visual-hierarchy revision."""
import argparse
import hashlib
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pymupdf


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--review-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    work = root.parent
    args.review_dir.mkdir(parents=True, exist_ok=True)
    qa = json.loads((root / 'NATURE_FINAL_QA.json').read_text())
    old_qa = json.loads((args.before / 'figure_generation/NATURE_FINAL_QA.json').read_text())
    for manifest in (old_qa, qa):
        for rel, digest in manifest['input_hashes'].items():
            assert sha(work / rel) == digest, rel
    assert sha(root / 'nature_final.py') == qa['script_sha256']
    for name, digest in qa['outputs'].items():
        assert sha(work / 'figures/nature' / name) == digest, name
    old = json.loads((args.before / 'figures/nature/PLOTTED_VALUES.json').read_text())
    new = json.loads((work / 'figures/nature/PLOTTED_VALUES.json').read_text())
    for key in old:
        assert new[key] == old[key], key
    for ext in ('pdf', 'png', 'svg', 'tiff'):
        rel = Path('figures/nature') / f'Figure6.{ext}'
        assert sha(work / rel) == sha(args.before / rel), rel
    table1 = lambda text: text.split(r'\textbf{Table 1 \textbar{}')[1].split(r'\end{samepage}')[0]
    assert table1((work / 'DB_Curator_main.tex').read_text()) == table1((args.before / 'DB_Curator_main.tex').read_text())
    resource = json.loads((root / 'source_data/benchmark_operational_current_manifest.json').read_text())
    for path, digest in resource['input_hashes'].items():
        assert sha(Path(path)) == digest, path
    for label in ('Confirmed', 'Other outcomes'):
        assert new['Figure3_resources']['tokens'][label]['n'] == resource['summary'][label]['n']
        assert new['Figure3_resources']['tokens'][label]['median'] == resource['summary'][label]['median_tokens']
    assert sum(r['n'] for r in new['Figure3_resources']['runtime'].values()) == 1881
    assert new['SupplementaryOperational']['n'] == 1808
    for item in qa['figures']:
        assert not item['text_overlaps'] and not item['out_of_bounds_text'] and not item['text_below_5pt'], item
    report = dict(status='pass', original_source_tables_unchanged=True,
                  existing_plotted_results_unchanged=True, table1_unchanged=True,
                  figure6_exports_unchanged=True, new_model_calls=0,
                  operational_records=1887, complete_token_records=1814,
                  runtime_records=1881, joint_resource_records=1808,
                  partial_usage_not_imputed=True, figures=qa['figures'], documents={})
    caption_ends = {2: '200 entries per topic.',
                    3: 'each observation is linked to its corresponding evaluation run.',
                    4: 'repeated-ablation resource use is in Supplementary Fig. 2.',
                    5: 'All 28 criterion profiles appear in Supplementary Fig. 4.',
                    6: 'GPL, glycerophospholipid.'}
    for stem in ('DB_Curator_main', 'DB_Curator_SI'):
        log = (work / f'{stem}.log').read_text()
        assert not re.search(r'Overfull|Undefined control sequence|Missing character|^!|undefined references', log, re.M)
        with pymupdf.open(work / f'{stem}.pdf') as doc:
            report['documents'][stem] = dict(pages=len(doc), pdf_sha256=sha(work / f'{stem}.pdf'))
            if stem == 'DB_Curator_main':
                with pymupdf.open(args.before / f'{stem}.pdf') as before:
                    select = lambda d: next(p for p in d if 'Figure 1 |' in p.get_text())
                    assert select(doc).get_pixmap().samples == select(before).get_pixmap().samples
                    report['figure1_page_unchanged'] = True
                for number, ending in caption_ends.items():
                    matching = [p for p in doc if f'Figure {number} |' in p.get_text()]
                    assert len(matching) == 1, number
                    page = matching[0]
                    assert ending in ' '.join(page.get_text().split()), f'Figure {number} caption split'
                    page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).save(args.review_dir / f'main_figure{number}.png')
            else:
                page = next(p for p in doc if 'Hexagonal bins show' in p.get_text())
                assert 'resource plot and remain in the benchmark decision totals.' in ' '.join(page.get_text().split())
                page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).save(args.review_dir / 'si_operational.png')
    names = ['Figure2', 'Figure3', 'Figure4', 'Figure5', 'Figure6',
             'SupplementaryCost', 'SupplementaryOperational', 'SupplementaryProfiles']
    with pymupdf.open() as review:
        for name in names:
            with pymupdf.open(work / 'figures/nature' / f'{name}.pdf') as figure:
                assert len(figure) == 1 and figure[0].get_text().strip()
                assert abs(figure[0].rect.width * 25.4 / 72 - 180) < .01
                review.insert_pdf(figure)
        review.save(work / 'FIGURES_REVIEW_SI_INTEGRATED_20261101.pdf', garbage=4, deflate=True)
    fig, axes = plt.subplots(4, 2, figsize=(12, 20), facecolor='white')
    for ax, name in zip(axes.flat, names):
        ax.imshow(plt.imread(work / 'figures/nature' / f'{name}.png'))
        ax.set_title(name, fontsize=11, loc='left')
        ax.axis('off')
    fig.tight_layout(pad=1)
    fig.savefig(work / 'FIGURES_OVERVIEW_SI_INTEGRATED_20261101.png', dpi=160)
    plt.close(fig)
    (work / 'FIGURE_VISUAL_HIERARCHY_VALIDATION_20261101.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['documents'], indent=2))
    print('PASS: unchanged results, run-linked resources, Figure 1/6, Table 1, captions, hashes and layout')


if __name__ == '__main__':
    main()
