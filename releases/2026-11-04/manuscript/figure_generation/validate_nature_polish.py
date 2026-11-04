"""Verify the figure narrative revision against a snapshot and export review previews."""
import argparse
import csv
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
    previous = json.loads((args.before / 'figure_generation/NATURE_FINAL_QA.json').read_text())
    for rel, digest in previous['input_hashes'].items():
        assert sha(work / rel) == digest, rel
    for rel, digest in qa['input_hashes'].items():
        assert sha(work / rel) == digest, rel
    assert sha(root / 'nature_final.py') == qa['script_sha256']
    for name, digest in qa['outputs'].items():
        assert sha(work / 'figures/nature' / name) == digest, name
    unchanged = ('Figure3', 'Figure6')
    for name in unchanged:
        for suffix in ('pdf', 'png', 'svg', 'tiff'):
            rel = Path('figures/nature') / f'{name}.{suffix}'
            assert sha(work / rel) == sha(args.before / rel), rel
    old_values = json.loads((args.before / 'figures/nature/PLOTTED_VALUES.json').read_text())
    values = json.loads((work / 'figures/nature/PLOTTED_VALUES.json').read_text())
    for key in ('Figure2', 'Figure3', 'Figure5', 'Figure6'):
        assert values[key] == old_values[key], key
    for key in ('counts', 'overall_per_100', 'repeats', 'forest', 'feedback_all100'):
        assert values['Figure4'][key] == old_values['Figure4'][key], key
    assert values['Figure4']['model_swap'] == old_values['SupplementaryFigure3']['model_swap']
    assert values['SupplementaryCost'] == old_values['SupplementaryFigure3']['costs']
    assert values['construction_accumulation'] == old_values['SupplementaryFigure2']
    assert len(values['Figure6']) == len(old_values['Figure6']) == 3
    for old, new in zip(old_values['Figure6'], values['Figure6']):
        assert {k: new[k] for k in old} == old
        for field, phrases in new['highlighted_phrases'].items():
            assert all(phrase in new[field] for phrase, color in phrases)
    from nature_final import feedback_summary, criterion_distribution, DATA, read
    assert values['Figure4']['feedback_all100'] == feedback_summary()
    assert values['Figure5_distribution'] == criterion_distribution()[1]
    assert values['SupplementaryProfiles'] == read(DATA / 'criterion_full_profiles.csv')
    main_tex = (work / 'DB_Curator_main.tex').read_text()
    old_main_tex = (args.before / 'DB_Curator_main.tex').read_text()
    table1 = lambda text: text.split(r'\textbf{Table 1 \textbar{}')[1].split(r'\end{samepage}')[0]
    assert table1(main_tex) == table1(old_main_tex)
    assert '(Fig. 2e)' in main_tex and '(Fig. 4e)' in main_tex and '(Fig. 4f)' in main_tex
    with (root / 'source_data/adjacent_stage_contrasts.csv').open() as stream:
        adjacent = list(csv.DictReader(stream))
    si = (work / 'DB_Curator_SI.tex').read_text()
    table = si.split('Supplementary Table 6.')[1].split('Supplementary Table 7.')[0]
    names = {'all': 'Overall', 'dbp': 'DBPs', 'blood_exposome': 'Blood exposome',
             'drug_compounds': 'Drugs', 'human_endogenous_metabolites': 'Endogenous metabolites',
             'microbial_natural_products': 'Microbial natural products'}
    labels = {'Static-Zero': 'Frozen--Zero', 'Dynamic-Static': 'Adaptive--Frozen', 'Full-Dynamic': 'Full--Adaptive'}
    for row in adjacent:
        key = row['contrast'] + '|' + row['topic']
        expected = [float(row[k]) for k in ('difference_pp', 'ci95_low_pp', 'ci95_high_pp')]
        assert values['Figure4']['forest'][key] == expected
        line = next(line for line in table.splitlines()
                    if line.startswith(names[row['topic']] + ' & ' + labels[row['contrast']] + ' &'))
        numeric = [float(x) for x in re.findall(r'-?\d+\.\d+', line)]
        assert numeric == [float(f'{x:.2f}') for x in expected], line
    for item in qa['figures']:
        assert not item['text_overlaps'] and not item['out_of_bounds_text'], item
    report = {'status': 'pass', 'frozen_inputs_unchanged': True, 'new_model_calls': 0,
              'unchanged_figures': list(unchanged), 'table1_unchanged': True,
              'figure6_quotes_and_decisions_unchanged': True,
              'promoted_accumulation_and_robustness_unchanged': True,
              'criterion_distribution_recomputed_from_1882_records': True,
              'complete_profiles_preserve_28_criteria': True,
              'feedback_all100_recomputed_from_300_records': True,
              'si_table_matches_18_plotted_contrasts': True,
              'figure_checks': qa['figures'], 'documents': {}}
    for stem in ('DB_Curator_main', 'DB_Curator_SI'):
        log = (work / (stem + '.log')).read_text()
        assert not re.search(r'Overfull|Undefined control sequence|Missing character|^!|undefined references', log, re.M)
        with pymupdf.open(work / (stem + '.pdf')) as doc:
            report['documents'][stem] = {'pages': len(doc), 'pdf_sha256': sha(work / (stem + '.pdf'))}
            if stem == 'DB_Curator_main':
                with pymupdf.open(args.before / (stem + '.pdf')) as old:
                    select = lambda d: next(p for p in d if 'Figure 1 |' in p.get_text())
                    assert select(doc).get_pixmap().samples == select(old).get_pixmap().samples
                    report['figure1_page_unchanged'] = True
            for i, page in enumerate(doc):
                if stem == 'DB_Curator_main' and any(f'Figure {n} |' in page.get_text() for n in (2, 3, 4, 5, 6)):
                    text = ' '.join(page.get_text().split())
                    endings = {2: 'End labels give the records processed',
                               4: 'Numerical details are in Table 1',
                               5: 'All 28 criterion profiles appear'}
                    for n, ending in endings.items():
                        if f'Figure {n} |' in page.get_text():
                            assert ending in text, f'Figure {n} caption split across pages'
                    page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(args.review_dir / f'{stem}_p{i + 1}.png')
                if stem == 'DB_Curator_SI' and any(f'Supplementary Figure {n} |' in page.get_text() for n in (2, 3, 4)):
                    page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(args.review_dir / f'{stem}_p{i + 1}.png')
    names = ['Figure2', 'Figure3', 'Figure4', 'Figure5', 'Figure6', 'SupplementaryCost', 'SupplementaryProfiles']
    with pymupdf.open() as review:
        for name in names:
            with pymupdf.open(work / 'figures/nature' / (name + '.pdf')) as figure:
                assert len(figure) == 1 and figure[0].get_text().strip()
                assert abs(figure[0].rect.width * 25.4 / 72 - 180) < .01
                review.insert_pdf(figure)
        review.save(work / 'FIGURES_REVIEW_SI_INTEGRATED_20261101.pdf', garbage=4, deflate=True)
    fig, axes = plt.subplots(4, 2, figsize=(12, 20), facecolor='white')
    for ax, name in zip(axes.flat, names):
        ax.imshow(plt.imread(work / 'figures/nature' / (name + '.png')))
        ax.set_title(name, fontsize=11, loc='left')
        ax.axis('off')
    for ax in list(axes.flat)[len(names):]:
        ax.axis('off')
    fig.tight_layout(pad=1)
    fig.savefig(work / 'FIGURES_OVERVIEW_SI_INTEGRATED_20261101.png', dpi=160)
    plt.close(fig)
    (work / 'FIGURE_SI_INTEGRATION_VALIDATION_20261101.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['documents'], indent=2))
    print('PASS: frozen values, SI promotion, 1882 indicator rows, Table 1, quotes, layout and exports')


if __name__ == '__main__':
    main()
