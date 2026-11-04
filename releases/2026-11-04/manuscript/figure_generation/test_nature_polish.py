"""Offline regression checks for figure values, intervals and rendering bounds."""
import json
import re
from unittest import TestCase, main
from unittest.mock import patch

import matplotlib.pyplot as plt
import pymupdf

import adjacent_contrasts as contrasts
import nature_final as figures


class FigureRegressionTests(TestCase):
    def test_round_half_up(self):
        self.assertEqual(figures.per_entry(321, 200), '1.61')
        self.assertEqual(figures.per_entry(331, 200), '1.66')
        self.assertEqual(figures.per_entry(707, 200), '3.54')

    def test_interval_cannot_be_silently_clipped(self):
        fig, ax = plt.subplots()
        try:
            ax.set_xlim(-25, 25)
            with self.assertRaises(AssertionError):
                figures.checked_interval(ax, 42.6667, 32, 53, 0, 'black')
            ax.set_xlim(-25, 60)
            figures.checked_interval(ax, 42.6667, 32, 53, 0, 'black')
        finally:
            plt.close(fig)

    def test_paired_bootstrap_reproducible(self):
        computed, _ = contrasts.compute()
        saved = contrasts.read(contrasts.DATA / 'adjacent_stage_contrasts.csv')
        self.assertEqual(len(computed), 18)
        for a, b in zip(computed, saved):
            self.assertEqual((a['topic'], a['contrast']), (b['topic'], b['contrast']))
            for key in ('difference_pp', 'ci95_low_pp', 'ci95_high_pp'):
                self.assertAlmostEqual(a[key], float(b[key]), places=9)
        overall = next(r for r in computed if r['topic'] == 'all' and r['contrast'] == 'Dynamic-Static')
        self.assertEqual((overall['a_confirmed'], overall['b_confirmed']), (648, 488))

    def test_review_counts_use_separate_columns_and_full_denominators(self):
        figures.style()
        with patch.object(figures, 'save') as saved:
            figures.figure2()
        canvas = saved.call_args.args[0]
        try:
            ax = next(ax for ax in canvas.fig.axes if ax.get_gid() == 'construction_expert_review')
            review = figures.VALUES['Figure2_review']
            cohorts = [review['construction_250_labeled_version'], review['zero_shot_250']]
            recall = figures.VALUES['Figure2_recall']
            self.assertEqual(len(ax.patches), 30)
            for i, topic in enumerate(figures.TOPICS):
                r = recall['topics'][topic]
                counts = [(cohort['topics'][topic]['agreement'], cohort['topics'][topic]['n'])
                          for cohort in cohorts] + [(r['TP'], r['TP'] + r['FN'])]
                for j, (n, denominator) in enumerate(counts):
                    agreed, disagreed = ax.patches[6*i+2*j:6*i+2*j+2]
                    self.assertAlmostEqual(agreed.get_width(), 18*n/denominator)
                    self.assertAlmostEqual(agreed.get_width()+disagreed.get_width(), 18)
                    self.assertEqual(agreed.get_y(), disagreed.get_y())
                self.assertEqual(len({ax.patches[6*i+2*j].get_x() for j in range(3)}), 3)
            texts = [t.get_text() for t in ax.texts]
            for expected in ['241/250', '248/250', '241/243', '45/50', '47/50', '49/50',
                             '50/52', '45/45', '47/47', '49/49', 'DB-Curator\nrecall']:
                self.assertIn(expected, texts)
            for removed in ['96.4%', '99.2%']:
                self.assertNotIn(removed, texts)
            self.assertNotIn('Zero-shot\nrecall', texts)
            self.assertEqual(recall['overall']['processed'], 359)
            self.assertEqual([recall['overall'][key] for key in ('TP', 'FP', 'FN', 'TN')],
                             [241, 9, 2, 107])
        finally:
            plt.close(canvas.fig)

    def test_citation_panel_matches_retained_citation_inventory(self):
        citations = figures.read(figures.ROOT.parent /
                                 'source_data/construction_completed_20261101/citation_instances.csv')
        papers = [row for row in citations if row['excluded_database_or_tool'] == 'False']
        self.assertEqual(len(citations) - len(papers), 5)
        self.assertEqual(len(papers), 7689)
        self.assertEqual(len({row['case_id'] for row in papers}), 1000)
        self.assertTrue(all(row['source_and_attributed_text_verified'] == 'True' for row in papers))
        data = {row['topic']: row for row in figures.read(figures.DATA / 'construction_final.csv')}
        for topic in figures.TOPICS:
            self.assertEqual(sum(row['topic'] == topic for row in papers),
                             int(data[topic]['verified_citations']))
        with patch.object(figures, 'save') as saved:
            figures.figure2()
        canvas = saved.call_args.args[0]
        try:
            ax = next(ax for ax in canvas.fig.axes if ax.get_gid() == 'citation_traceability')
            self.assertEqual(ax.get_xlabel(), 'Matched paper and passage (%)')
            self.assertIn('Matched / cited', [t.get_text() for t in ax.texts])
        finally:
            plt.close(canvas.fig)

    def test_figure2_and_complete_caption_share_page(self):
        with pymupdf.open(figures.ROOT.parent / 'DB_Curator_main.pdf') as doc:
            pages = [' '.join(page.get_text().split()) for page in doc]
        captions = [text for text in pages if
                    'Database construction, citation traceability and expert review.' in text]
        self.assertEqual(len(captions), 1)
        self.assertIn('Paper and quotation checks', captions[0])
        self.assertIn('DB-Curator processed-pool recall is 241/243 (99.2%).', captions[0])

    def test_merged_construction_preserves_counts_ratios_and_curves(self):
        figures.style()
        with patch.object(figures, 'save') as saved:
            figures.figure2()
        canvas = saved.call_args.args[0]
        try:
            data = figures.VALUES['Figure2']
            labels = [t.get_text() for t in canvas.fig.texts]
            self.assertEqual([t for t in labels if t in list('abcdef')], list('abcde'))
            ax = next(ax for ax in canvas.fig.axes if ax.get_gid() == 'construction_trajectory')
            for i, topic in enumerate(figures.TOPICS):
                row = data[topic]
                self.assertIn(str(row['processed_candidates']), labels)
                self.assertIn(figures.per_entry(row['processed_candidates'], row['final_confirmed']), labels)
                line = ax.lines[2*i]
                self.assertEqual(line.get_xdata()[-1], row['processed_candidates'])
                self.assertEqual(line.get_ydata()[-1], row['final_confirmed'])
        finally:
            plt.close(canvas.fig)

    def test_benchmark_comparison_uses_paired_bars_without_squares(self):
        figures.style()
        with patch.object(figures, 'save') as saved:
            figures.figure2()
        canvas = saved.call_args.args[0]
        try:
            ax = next(ax for ax in canvas.fig.axes if ax.get_gid() == 'benchmark_method_comparison')
            self.assertEqual(len(ax.patches), 10)
            self.assertEqual(ax.get_xlim(), (0, 100))
            for i, topic in enumerate(figures.TOPICS):
                row = figures.VALUES['Figure2'][topic]
                db, zero = ax.patches[2*i:2*i+2]
                self.assertAlmostEqual(db.get_width(), 100*row['released_benchmark_linked']/row['final_confirmed'])
                self.assertAlmostEqual(zero.get_width(), 100*row['zero_shot_benchmark_linked']/row['zero_shot_candidates'])
                self.assertLess(db.get_y(), zero.get_y())
            self.assertFalse(any(line.get_marker() == 's' for a in canvas.fig.axes for line in a.lines))
        finally:
            plt.close(canvas.fig)

    def test_benchmark_review_keeps_its_own_cohort(self):
        summary = figures.benchmark_review_topics()
        self.assertEqual(sum(v['n'] for v in summary.values()),1886)
        self.assertEqual(sum(v['agreement'] for v in summary.values()),1870)
        self.assertEqual(summary['human_endogenous_metabolites'],dict(n=299,agreement=288))

    def test_overall_contrasts_share_one_scale(self):
        with patch.object(figures, 'save') as saved:
            figures.figure4()
        canvas = saved.call_args.args[0]
        try:
            axes = [ax for ax in canvas.fig.axes if ax.get_gid() == 'overall_stage_contrasts']
            self.assertEqual(len(axes), 1)
            ax = axes[0]
            self.assertEqual(len(ax.lines), 4)  # zero line plus one marker per contrast
            self.assertEqual(len(ax.patches), 3)
            self.assertEqual(len(ax.collections), 0)
            expected_gains = [11.4, 10.666666666666666, 1.6666666666666667]
            for bar, expected in zip(ax.patches, expected_gains):
                self.assertAlmostEqual(bar.get_x(), 0)
                self.assertAlmostEqual(bar.get_width(), expected)
            xmin, xmax = ax.get_xlim()
            for line in ax.lines[1:]:
                self.assertGreater(min(line.get_xdata()), xmin)
                self.assertLess(max(line.get_xdata()), xmax)
            expected = {r['contrast'] + '|all': tuple(float(r[k]) for k in
                        ('difference_pp', 'ci95_low_pp', 'ci95_high_pp'))
                        for r in figures.read(figures.DATA / 'adjacent_stage_contrasts.csv')
                        if r['topic'] == 'all'}
            self.assertEqual(figures.VALUES['Figure4']['forest'], expected)
            self.assertEqual(len(figures.read(figures.DATA / 'adjacent_stage_contrasts.csv')), 18)
        finally:
            plt.close(canvas.fig)

    def test_merged_model_table_preserves_estimates_and_spread(self):
        with patch.object(figures, 'save') as saved:
            figures.figure4()
        canvas = saved.call_args.args[0]
        try:
            labels = [t.get_text() for t in canvas.fig.texts]
            table = figures.VALUES['Figure4']['model_table']
            self.assertEqual(len(table), 10)
            for row in table:
                for key in ('adaptive', 'full'):
                    self.assertIn(f'{float(row[key]):.1f} ± {float(row[key+"_sd"]):.1f}', labels)
                self.assertIn(f'{float(row["change_pp"]):+.1f}', labels)
            self.assertEqual(canvas.h, 180)
        finally:
            plt.close(canvas.fig)

    def test_figure4_feedback_numeric_rows_align(self):
        with patch.object(figures, 'save') as saved:
            figures.figure4()
        canvas = saved.call_args.args[0]
        try:
            texts = canvas.fig.texts
            labels = ['A  Criterion-directed', 'B  General review', 'C  No explicit rubric']
            for row, label in zip(figures.feedback_summary(), labels):
                anchor = next(t for t in texts if t.get_text() == label)
                same_row = [t.get_text() for t in texts if t.get_position()[1] == anchor.get_position()[1]]
                for key, fmt in [('confirmed', '.1f'), ('mean_rounds', '.2f'),
                                 ('mean_tokens', ',.0f'), ('mean_accounted_usd', '.4f'),
                                 ('mean_source_files', '.1f')]:
                    self.assertIn(format(row[key], fmt), same_row)
        finally:
            plt.close(canvas.fig)

    def test_original_table1_numbers_survive_merge(self):
        original = (figures.TABLE1 / 'table1_original.tex').read_text()
        with pymupdf.open(figures.OUT / 'Figure4.pdf') as doc:
            text = ''.join(doc[0].get_text().split())
        for mean, sd in re.findall(r'\$([\d.]+)\\pm([\d.]+)\$', original):
            self.assertIn(mean + '±' + sd, text)
        for row in figures.read(figures.TABLE1 / 'feedback_statistics.csv'):
            for arm in 'ABC':
                self.assertIn(row[arm], text)
        for row in figures.read(figures.TABLE1 / 'component_statistics.csv'):
            self.assertIn(f'{float(row["min"]):.0f}–{float(row["max"]):.0f}', text)
            self.assertIn(f'{float(row["agreement"]):.1f}', text)
        main = (figures.ROOT.parent / 'DB_Curator_main.tex').read_text()
        self.assertNotRegex(main, r'(?<!Supplementary )Table 1')

    def test_figure4_caption_stays_with_artwork(self):
        with pymupdf.open(figures.ROOT.parent / 'DB_Curator_main.pdf') as doc:
            pages = [p for p in doc if 'Figure 4 |' in p.get_text()]
            self.assertEqual(len(pages), 1)
            text = ' '.join(pages[0].get_text().split())
            self.assertIn('Feedback mechanisms and research activity', text)
            self.assertIn('Repeated-ablation resource use appears in Supplementary Fig. 2.', text)

    def test_operational_records_and_completeness(self):
        data = figures.operational_rows()
        self.assertEqual(len(data), 1887)
        self.assertEqual(sum(r['final_label'] == 'Confirmed' for r in data), 975)
        complete = [r for r in data if r['token_status'] == 'complete_recorded_usage']
        timed = [r for r in data if r['runtime_status'] == 'recorded']
        self.assertEqual(len(complete), 1887)
        self.assertEqual(len(timed), 1887)
        self.assertTrue(all(int(r['unknown_usage_calls']) == 0 for r in complete))
        self.assertEqual(sum(r['runtime_status'] == 'recorded' for r in complete), 1887)
        self.assertTrue(all(float(r['duration_sec']) > 0 for r in timed))
        self.assertTrue(all(r['resource_source_sha256'] and r['final_record_sha256'] for r in data))

    def test_operational_values_fit_axes(self):
        figures.style()
        with patch.object(figures, 'save') as saved:
            figures.figure3()
        canvas = saved.call_args.args[0]
        try:
            d = next(ax for ax in canvas.fig.axes if ax.get_gid() == 'prediction_token_density')
            e = next(ax for ax in canvas.fig.axes if ax.get_gid() == 'token_runtime_relationship')
            for r in figures.operational_rows():
                if r['token_status'] == 'complete_recorded_usage':
                    value = figures.np.log10(float(r['tokens']))
                    self.assertLess(d.get_xlim()[0], value)
                    self.assertGreater(d.get_xlim()[1], value)
                if r['runtime_status'] == 'recorded' and r['token_status'] == 'complete_recorded_usage':
                    value = figures.np.log10(float(r['duration_sec']) / 60)
                    self.assertLess(e.get_ylim()[0], value)
                    self.assertGreater(e.get_ylim()[1], value)
                    token = figures.np.log10(float(r['tokens']))
                    self.assertLess(e.get_xlim()[0], token)
                    self.assertGreater(e.get_xlim()[1], token)
            paired = figures.VALUES['Figure3_resource_relationship']
            previous = json.loads((figures.OUT / 'PLOTTED_VALUES.json').read_text())['SupplementaryOperational']
            self.assertEqual(paired, previous)
            self.assertEqual(int(e.collections[0].get_array().sum()), 1887)
        finally:
            plt.close(canvas.fig)

    def test_supplementary_runtime_preserves_all_topic_distributions(self):
        figures.style()
        with patch.object(figures, 'save') as saved:
            figures.supplementary_runtime()
        canvas = saved.call_args.args[0]
        try:
            ax = next(ax for ax in canvas.fig.axes if ax.get_gid() == 'topic_runtime_distribution')
            summary = figures.VALUES['SupplementaryRuntime']
            previous = json.loads((figures.OUT / 'PLOTTED_VALUES.json').read_text())['Figure3_resources']['runtime']
            self.assertEqual(summary, previous)
            self.assertEqual(sum(r['n'] for r in summary.values()), 1887)
            for r in figures.operational_rows():
                if r['runtime_status'] == 'recorded':
                    value = figures.np.log10(float(r['duration_sec']) / 60)
                    self.assertLess(ax.get_ylim()[0], value)
                    self.assertGreater(ax.get_ylim()[1], value)
        finally:
            plt.close(canvas.fig)

    def test_feedback_counts_and_all100_resource_means(self):
        records = figures.feedback_summary()
        self.assertEqual([r['n'] for r in records], [100, 100, 100])
        self.assertEqual([r['confirmed'] for r in records], [58, 48, 51])
        self.assertEqual([r['unfinished'] for r in records], [2, 1, 0])
        self.assertEqual([r['mean_rounds'] for r in records], [1.62, 1.08, 1.07])
        self.assertEqual([r['mean_tokens'] for r in records], [209137.8, 172190.21, 148994.6])

    def test_highlighting_preserves_text(self):
        figures.style()
        fig, ax = plt.subplots()
        ax.set(xlim=(0, 100), ylim=(0, 30))
        sentence = 'Exact identity is required. PC(20:3/20:1) is not PC(20:2/20:1).'
        try:
            lines = figures.highlighted_text(ax, 0, 28, 35, sentence,
                                            [('PC(20:3/20:1)', figures.ROSE)])
            self.assertGreater(lines, 1)
            self.assertEqual(''.join(t.get_text() for t in ax.texts), sentence)
            self.assertTrue(any(t.get_color() == figures.ROSE for t in ax.texts))
            with self.assertRaises(AssertionError):
                figures.highlighted_text(ax, 0, 28, 35, sentence, [('not in source', figures.ROSE)])
        finally:
            plt.close(fig)

    def test_figure6_uses_complete_saved_quotes(self):
        cases = {r['candidate']: r for r in json.loads(figures.CASES.read_text())}
        specs = figures.case_specs()
        self.assertEqual(len(specs), 3)
        self.assertEqual(sum(len(r['source_anchors']) for r in specs), 7)
        for r in specs:
            anchors = [a for ins in cases[r['candidate']]['inspections'] for a in ins['source_anchors']]
            for i in (0, 1):
                self.assertEqual(r['quote' + str(i)], r['source_anchors'][i]['quote'])
                self.assertNotIn('…', r['quote' + str(i)])
            for a in r['source_anchors']:
                self.assertIn(a, anchors)
                self.assertEqual(a['location_status'], 'exact')
                self.assertIn(a['quote'], a['source_context'])
            self.assertEqual(r['final_label'], 'Confirmed')
        self.assertIn('Aspergillus carneus', specs[1]['context_quote0'])

    def test_figure6_criterion_transitions_follow_source_inspection(self):
        figures.style()
        with patch.object(figures, 'save') as saved:
            figures.figure6()
        canvas = saved.call_args.args[0]
        try:
            self.assertLess(canvas.h, 175)
            specs = figures.VALUES['Figure6']
            self.assertEqual([[r[1] for r in s['criteria']] for s in specs],
                             [[False],[False],[False]])
            self.assertEqual([[r[2] for r in s['criteria']] for s in specs],
                             [[True],[True],[False]])
            self.assertEqual([len(s['context_criteria']) for s in specs], [1,2,1])
            plotted_text = '\n'.join(t.get_text() for ax in canvas.fig.axes for t in ax.texts)
            for spec in specs:
                for criterion, before, after, summary in spec['context_criteria']:
                    self.assertTrue(before and after)
                    self.assertNotIn(criterion, plotted_text)
                    self.assertNotIn(summary, plotted_text)
            self.assertIn('intermediates between NOM',specs[0]['evidence_sentence'])
            self.assertIn('Isoterrelumamide A (67)',specs[1]['evidence_sentence'])
            self.assertIn('secondary metabolites',specs[1]['evidence_sentence'])
            self.assertIn('phosphatidylcholine (PC) biosynthesis',specs[2]['evidence_sentence'])
            self.assertNotIn('20:2',specs[2]['evidence_sentence'])
            for ax in canvas.fig.axes:
                self.assertTrue(all(t.get_fontsize() >= 6.1 for t in ax.texts))
        finally:
            plt.close(canvas.fig)

    def test_figure6_export_preserves_and_displays_verbatim_sentences(self):
        normal = lambda text: ''.join(text.split())
        archived=json.loads((figures.OUT/'Figure6_evidence_full.json').read_text())
        for r in figures.case_specs():
            for a in r['source_anchors']:
                self.assertIn(a['quote'],[x['quote'] for x in archived if x['candidate']==r['candidate']])
        with pymupdf.open(figures.OUT / 'Figure6.pdf') as doc:
            text = normal(doc[0].get_text())
            for r in figures.criterion_case_specs():
                self.assertIn(normal(r['evidence_summary']),text)
                for doi in r['source_ids']:self.assertIn(doi,text)
        with pymupdf.open(figures.ROOT.parent / 'DB_Curator_main.pdf') as doc:
            pages = [p for p in doc if 'How review changes criterion-level evidence' in p.get_text()]
            self.assertEqual(len(pages), 1)
            text = normal(pages[0].get_text())
            for r in figures.criterion_case_specs():
                self.assertIn(normal(r['evidence_summary']),text)
            self.assertIn('SupplementaryNote13', text)
            self.assertIn('SourceData',text)

    def test_figure6_sentences_and_highlights_match_original_sources(self):
        from xml.etree import ElementTree
        for record in figures.criterion_case_specs():
            source = record['verbatim_source']
            path = figures.ROOT.parent / source['source_file']
            self.assertEqual(figures.hashlib.sha256(path.read_bytes()).hexdigest(), source['source_sha256'])
            if path.suffix == '.xml':
                paragraphs = [''.join(el.itertext()) for el in ElementTree.parse(path).iter('p')]
                self.assertIn(source['source_context'], paragraphs)
            else:
                self.assertEqual(source['source_context'], json.loads(path.read_text())['abstract'])
            self.assertIn(record['evidence_sentence'], source['source_context'])
            self.assertNotIn('…', record['evidence_sentence'])
            for phrase, color in record['evidence_highlights']:
                self.assertIn(phrase, record['evidence_sentence'])
                self.assertEqual(color, record['color'])

    def test_highlighting_wraps_downward_on_inverted_axis(self):
        figures.style()
        fig, ax = plt.subplots()
        ax.set(xlim=(0,100), ylim=(30,0))
        sentence = 'The original sentence remains intact when it wraps across multiple lines.'
        try:
            figures.highlighted_text(ax, 0, 2, 25, sentence, [('original sentence', figures.SYSTEM)])
            ys = [text.get_position()[1] for text in ax.texts]
            self.assertEqual(ys, sorted(ys))
            self.assertGreater(len(set(ys)),1)
            self.assertEqual(''.join(text.get_text() for text in ax.texts), sentence)
        finally:
            plt.close(fig)

    def test_promoted_repeat_and_resource_values(self):
        values = json.loads((figures.OUT / 'PLOTTED_VALUES.json').read_text())
        self.assertEqual(values['Figure4']['repeats'], figures.read(figures.STORY / 'repeats.csv'))
        self.assertEqual(values['Figure4']['model_swap'], figures.read(figures.STORY / 'model_swap.csv'))
        self.assertEqual(values['SupplementaryCost'], {r['condition']: r for r in figures.read(figures.STORY / 'costs.csv')})

    def test_indicator_distributions_reproduce_all_rows(self):
        raw, dist = figures.criterion_distribution()
        self.assertEqual(len(raw), 1887)
        self.assertEqual(sum(int(r['row_count']) for r in dist), 1887)
        self.assertEqual(sum(int(r['row_count']) for r in dist if r['outcome'] == 'Confirmed'), 975)
        for topic in figures.TOPICS:
            self.assertAlmostEqual(sum(float(r['topic_fraction_percent']) for r in dist if r['topic'] == topic), 100)

    def test_full_profiles_preserve_selected_values(self):
        full = {(r['topic'], r['criterion']): r for r in figures.read(figures.DATA / 'criterion_full_profiles.csv')}
        self.assertEqual(len(full), 28)
        for selected in figures.read(figures.DATA / 'criterion_indicators.csv'):
            r = full[(selected['topic'], selected['criterion'])]
            for key in ('pass_rate_confirmed', 'pass_rate_other', 'rows_confirmed', 'rows_other'):
                self.assertAlmostEqual(float(selected[key]), float(r[key]))

    def test_promoted_accumulation_endpoints(self):
        values = json.loads((figures.OUT / 'PLOTTED_VALUES.json').read_text())
        for topic in figures.TOPICS:
            last = values['construction_accumulation'][topic]
            self.assertEqual(int(last['retained_rows']), 200)
            self.assertEqual(int(last['processed_records']), values['Figure2'][topic]['processed_candidates'])

    def test_exported_text_layout(self):
        qa = json.loads((figures.ROOT / 'NATURE_FINAL_QA.json').read_text())
        for figure in qa['figures']:
            with self.subTest(figure=figure['figure']):
                self.assertFalse(figure['text_overlaps'])
                self.assertFalse(figure['out_of_bounds_text'])
                self.assertFalse(figure['text_below_5pt'])

    def test_explanatory_notes_are_not_inside_figure_exports(self):
        forbidden = ('Repeated component ablation:', 'Same-state feedback comparison:',
                     '200 retained', '200 per topic', 'target: 200 entries per topic',
                     'Overall: DB-Curator', 'Overall agreement:')
        qa = json.loads((figures.ROOT / 'NATURE_FINAL_QA.json').read_text())
        for record in qa['figures']:
            with pymupdf.open(figures.OUT / (record['figure'] + '.pdf')) as doc:
                text = ' '.join(' '.join(p.get_text() for p in doc).split())
            for phrase in forbidden:
                self.assertNotIn(phrase, text, record['figure'])
        caption = (figures.ROOT.parent / 'DB_Curator_main.tex').read_text()
        self.assertIn('same 500 candidates (100 per topic) in three repeats', caption)
        self.assertIn('Panel d uses all 100 assigned candidates per arm', caption)

    def test_figures2_and3_have_readable_text(self):
        for name in ('Figure2', 'Figure3'):
            with pymupdf.open(figures.OUT / (name + '.pdf')) as doc:
                for page in doc:
                    for block in page.get_text('dict')['blocks']:
                        for line in block.get('lines', []):
                            for span in line['spans']:
                                if span['text'].strip():
                                    self.assertGreaterEqual(span['size'], 6.29, (name, span['text']))

    def test_indicator_labels_and_review_cohort_are_explicit(self):
        for name in ('Figure5', 'SupplementaryProfiles'):
            with pymupdf.open(figures.OUT / (name + '.pdf')) as doc:
                text = ' '.join(' '.join(p.get_text() for p in doc).split())
            self.assertIn('Recorded criterion indicator', text)
            self.assertNotIn('Positive indicators', text)
        main = (figures.ROOT.parent / 'DB_Curator_main.tex').read_text()
        self.assertIn('Among the reviewed Confirmed predictions, 98.9', main)
        self.assertIn('final researcher predictions', main.lower())
        self.assertIn('Panel b summarizes the expert-reviewed archived outputs', main)
        self.assertIn('965/976', (figures.ROOT.parent / 'DB_Curator_SI.tex').read_text())
        self.assertIn('241/250 (96.4', main)
        self.assertIn('1,870/1,886 reviewed outputs', main)

    def test_confidence_intervals_not_presented_in_manuscript(self):
        forbidden = ('confidence interval', '95% interval', '95% ci', 'bootstrap', 'whisker',
                     'positive indicator')
        for name in ('DB_Curator_main', 'DB_Curator_SI'):
            source = (figures.ROOT.parent / (name + '.tex')).read_text().lower().replace('\\%', '%')
            with pymupdf.open(figures.ROOT.parent / (name + '.pdf')) as doc:
                rendered = ' '.join(' '.join(p.get_text() for p in doc).lower().split())
            for phrase in forbidden:
                self.assertNotIn(phrase, source, name)
                self.assertNotIn(phrase, rendered, name)


if __name__ == '__main__':
    main()
