"""Test grouping with the evaluator's actual statistics function, without network execution."""
import ast
import json
from pathlib import Path
import unittest
import numpy as np
from probability_profile import selection_profile


def load_group():
    tree = ast.parse(Path(__file__).with_name('evaluate_paper.py').read_text())
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'group']
    if len(nodes) != 1:
        raise ValueError('Expected exactly one evaluator group function')
    namespace = {'np': np}
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), '<evaluator group>', 'exec'), namespace)
    return namespace['group']


class ProbabilityProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.group = staticmethod(load_group())

    def profile(self, rows):
        return selection_profile(rows, self.group)

    def test_home_and_away_favorites(self):
        report = self.profile([{'p': .70, 'won': 1}, {'p': .20, 'won': 0}])
        self.assertEqual(report['selected']['n'], 2)
        self.assertEqual(report['selected']['observed_win_rate'], 1)
        self.assertAlmostEqual(report['selected']['mean_probability'], .75)
        self.assertAlmostEqual(report['selected']['brier'], .065)

    def test_threshold_boundaries_and_no_double_count(self):
        rows = [{'p': p, 'won': 1} for p in [.64, .65, .70, .75, .80, 1.0]]
        report = self.profile(rows)
        self.assertEqual(report['selected']['n'], 5)
        self.assertEqual(report['games_below_profile'], 1)
        self.assertEqual([b['n'] for b in report['bands']], [1, 1, 1, 2])

    def test_away_threshold(self):
        report = self.profile([{'p': .35, 'won': 0}, {'p': .36, 'won': 1}])
        self.assertEqual(report['selected']['n'], 1)
        self.assertAlmostEqual(report['selected']['mean_probability'], .65)

    def test_empty_profile_is_not_a_zero_hit_rate(self):
        report = self.profile([])
        self.assertIsNone(report['selected']['observed_win_rate'])
        self.assertEqual(sum(b['n'] for b in report['bands']), 0)
        json.dumps(report, allow_nan=False)

    def test_losses_are_not_filtered_out(self):
        report = self.profile([{'p': .70, 'won': 0}, {'p': .20, 'won': 1}])
        self.assertEqual(report['selected']['n'], 2)
        self.assertEqual(report['selected']['observed_win_rate'], 0)
        self.assertAlmostEqual(report['selected']['brier'], .565)

    def test_market_prices_cannot_change_groups(self):
        a = [{'p': .7, 'won': 1, 'odds': 1.01}]
        b = [{'p': .7, 'won': 1, 'odds': 1000.0}]
        self.assertEqual(self.profile(a), self.profile(b))

    def test_invalid_probabilities_rejected(self):
        for p in [float('nan'), float('inf'), -.01, 1.01, True]:
            with self.subTest(p=p), self.assertRaises(ValueError):
                self.profile([{'p': p, 'won': 1}])

    def test_invalid_outcomes_rejected(self):
        for won in [None, -1, 2, True]:
            with self.subTest(won=won), self.assertRaises(ValueError):
                self.profile([{'p': .7, 'won': won}])

    def test_no_mutation_or_automatic_release(self):
        rows = [{'p': .99, 'won': 1}]
        before = json.dumps(rows)
        report = self.profile(rows)
        self.assertEqual(json.dumps(rows), before)
        self.assertIs(report['betting_release'], False)
        self.assertIs(report['calibration_validated'], False)

    def test_only_one_side_per_game(self):
        report = self.profile([{'p': .99, 'won': 1}, {'p': .01, 'won': 0}])
        self.assertEqual(report['games_scored'], 2)
        self.assertEqual(report['selected']['n'], 2)
        self.assertEqual(sum(b['n'] for b in report['bands']), 2)


if __name__ == '__main__':
    unittest.main()
