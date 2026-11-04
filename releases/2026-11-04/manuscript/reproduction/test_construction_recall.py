import csv
import json
import unittest

from calculate_construction_recall import OUT, summarize


class ConstructionRecallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (OUT / 'construction_review_359_rows.csv').open(encoding='utf-8-sig') as handle:
            cls.rows = list(csv.DictReader(handle))

    def test_distinct_same_cohort_records(self):
        self.assertEqual(len(self.rows), 359)
        self.assertEqual(len({(r['topic'], r['results_dir']) for r in self.rows}), 359)
        self.assertEqual(sum(r['system_retained'] == 'True' for r in self.rows), 250)

    def test_overall_counts_and_standard_recall(self):
        result = summarize('all', self.rows)
        self.assertEqual([result[k] for k in ['TP', 'FP', 'FN', 'TN']], [241, 9, 2, 107])
        self.assertAlmostEqual(result['precision'], 241/250)
        self.assertAlmostEqual(result['processed_pool_recall'], 241/243)
        self.assertNotEqual(result['processed_pool_recall'], (359-2)/359)

    def test_false_negatives_follow_explicit_author_clarification(self):
        confirmation = json.loads((OUT / 'AUTHOR_CONFIRMATION.json').read_text())
        self.assertTrue(confirmation['blood_two_are_false_negatives'])
        fn = {r['candidate_name'] for r in self.rows if r['confusion_cell'] == 'FN'}
        self.assertEqual(fn, set(confirmation['false_negative_candidates']))

    def test_topic_negative_counts(self):
        expected = {'dbp': 72, 'blood_exposome': 14, 'drug_compounds': 1,
                    'human_endogenous_metabolites': 15, 'microbial_natural_products': 7}
        for topic, n in expected.items():
            selected = [r for r in self.rows if r['topic'] == topic]
            self.assertEqual(summarize(topic, selected)['nonconfirmed'], n)

    def test_recovered_confirmed_label_preserves_human_agreement(self):
        recovered = [r for r in self.rows if r['native_label_recovery_used'] == 'True']
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]['candidate_name'], 'benzalkonium chloride')
        self.assertEqual(recovered[0]['confusion_cell'], 'TP')


if __name__ == '__main__':
    unittest.main()
