"""Synthetic collector contract tests; no live-source or model validation."""
import copy
import datetime as dt
import unittest
from unittest.mock import Mock
from reference_import import collect_references, SELECTIONS


class ReferenceImportTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 20, 10, tzinfo=dt.timezone.utc)
        self.f = {'game_id': '0022600043', 'home': 'ATL', 'away': 'CHA',
                  'start_time_utc': '2026-11-21T00:00:00Z'}
        self.paper = {'forecasts': [self.f], 'protocol': 'test'}

    def offer(self, market='moneyline', side='home', gid=None):
        return {'game_id': gid or self.f['game_id'], 'market': market, 'side': side,
                'line': None if market == 'moneyline' else 5.5,
                'odds': 1.9, 'bookmaker': 'Example', 'source': 'https://example.org/odds',
                'price_timestamp_utc': None, 'rules_verified': False, 'betting_release': False}

    def test_empty_primary_uses_fallback(self):
        row = self.offer()
        secondary = Mock(return_value=([row], []))
        rows, errors = collect_references(self.paper, self.now,
            Mock(return_value=([], [{'source': 'https://www.covers.com', 'rejected_cells': 36}])), secondary)
        self.assertEqual(rows, [row])
        self.assertEqual(errors[0]['rejected_cells'], 36)
        self.assertEqual(errors[-1]['fallback_offers_added'], 1)
        self.assertEqual(errors[-1]['missing_selection_groups_after'], 5)
        secondary.assert_called_once()

    def test_complete_primary_does_not_call_fallback(self):
        rows = [self.offer(m, s) for m, s in sorted(SELECTIONS)]
        secondary = Mock(side_effect=AssertionError('unexpected fallback'))
        self.assertEqual(collect_references(self.paper, self.now,
            Mock(return_value=(rows, [])), secondary), (rows, []))
        secondary.assert_not_called()

    def test_partial_primary_preserved_and_opposite_side_filled(self):
        home, away = self.offer(), self.offer(side='away')
        duplicate = dict(home, odds=2.1)
        rows, _ = collect_references(self.paper, self.now,
            Mock(return_value=([home], [])), Mock(return_value=([duplicate, away], [])))
        self.assertEqual(rows, [home, away])
        self.assertEqual(rows[0]['odds'], 1.9)

    def test_fallback_only_requests_games_with_missing_selections(self):
        other = dict(self.f, game_id='0022600044')
        primary = [self.offer(m, s) for m, s in sorted(SELECTIONS)]
        secondary = Mock(return_value=([], []))
        collect_references(dict(self.paper, forecasts=[self.f, other]), self.now,
            Mock(return_value=(primary, [])), secondary)
        self.assertEqual(secondary.call_args.args[0]['forecasts'], [other])

    def test_unrelated_fallback_game_not_imported(self):
        rows, _ = collect_references(self.paper, self.now, Mock(return_value=([], [])),
            Mock(return_value=([self.offer(gid='unrelated')], [])))
        self.assertEqual(rows, [])

    def test_primary_exception_still_attempts_fallback(self):
        row = self.offer()
        rows, errors = collect_references(self.paper, self.now,
            Mock(side_effect=OSError('primary down')), Mock(return_value=([row], [])))
        self.assertEqual(rows, [row])
        self.assertIn('primary down', errors[0]['error'])

    def test_fallback_exception_preserves_primary(self):
        row = self.offer()
        rows, errors = collect_references(self.paper, self.now,
            Mock(return_value=([row], [])), Mock(side_effect=OSError('secondary down')))
        self.assertEqual(rows, [row])
        self.assertTrue(any('secondary down' in e.get('error', '') for e in errors))

    def test_both_sources_empty_remain_empty_and_explicit(self):
        rows, errors = collect_references(self.paper, self.now,
            Mock(return_value=([], [])), Mock(return_value=([], [])))
        self.assertEqual(rows, [])
        self.assertEqual(errors[-1]['missing_selection_groups_after'], 6)
        self.assertIn('No matching', errors[-1]['error'])

    def test_duplicates_removed(self):
        row = self.offer()
        rows, errors = collect_references(self.paper, self.now,
            Mock(return_value=([], [])), Mock(return_value=([row, dict(row)], [])))
        self.assertEqual(rows, [row])
        self.assertEqual(errors[-1]['fallback_offers_added'], 1)

    def test_source_price_and_safety_flags_preserved(self):
        row = self.offer()
        rows, _ = collect_references(self.paper, self.now,
            Mock(return_value=([], [])), Mock(return_value=([row], [])))
        self.assertEqual(rows[0], row)
        self.assertFalse(rows[0]['betting_release'])
        self.assertFalse(rows[0]['rules_verified'])
        self.assertIsNone(rows[0]['price_timestamp_utc'])

    def test_started_games_do_not_trigger_requests(self):
        primary, secondary = Mock(), Mock()
        paper = dict(self.paper, forecasts=[dict(self.f, start_time_utc=self.now.isoformat())])
        self.assertEqual(collect_references(paper, self.now, primary, secondary), ([], []))
        primary.assert_not_called()
        secondary.assert_not_called()

    def test_inputs_not_mutated(self):
        paper = copy.deepcopy(self.paper)
        row = self.offer()
        original = copy.deepcopy(row)
        collect_references(paper, self.now, Mock(return_value=([row], [])), Mock(return_value=([], [])))
        self.assertEqual(paper, self.paper)
        self.assertEqual(row, original)


if __name__ == '__main__':
    unittest.main()
