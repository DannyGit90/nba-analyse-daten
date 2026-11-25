"""Synthetic unit tests; probabilities are not NBA forecasts."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from winner_snapshot_audit import PROTOCOL, audit, main


def sample():
    return {'protocol': PROTOCOL, 'execution_ok': True,
            'generated_at_utc': '2026-11-17T20:54:59+00:00',
            'forecasts': [{'game_id': '0022600253',
                'start_time_utc': '2026-11-18T00:30:00+00:00',
                'home_team_id': '1610612761', 'away_team_id': '1610612752',
                'home': 'TOR', 'away': 'NYK',
                'p_home_experimental': .4, 'p_away_experimental': .6}]}


class WinnerSnapshotTests(unittest.TestCase):
    def test_valid_and_no_mutation(self):
        source = sample()
        before = copy.deepcopy(source)
        result = audit(source)
        self.assertEqual(result['status'], 'formal_consistent')
        self.assertEqual(source, before)
        self.assertFalse(result['betting_release'])
        self.assertEqual(result['probability_validation'], 'not_assessed')

    def test_protocol_and_execution(self):
        for key, value in [('protocol', 'other'), ('execution_ok', False)]:
            with self.subTest(key=key):
                source = sample()
                source[key] = value
                self.assertEqual(audit(source)['status'], 'invalid')

    def test_bad_root_and_forecasts(self):
        with self.assertRaises(ValueError):
            audit([])
        self.assertEqual(audit(dict(sample(), forecasts={} ))['status'], 'invalid')
        self.assertEqual(audit(dict(sample(), forecasts=[None]))['status'], 'invalid')

    def test_empty_is_not_a_pass(self):
        self.assertEqual(audit(dict(sample(), forecasts=[]))['status'], 'no_forecasts')

    def test_duplicates_invalidate_both(self):
        source = sample()
        source['forecasts'] *= 2
        self.assertEqual(audit(source)['consistent_count'], 0)

    def test_team_and_game_identity(self):
        for key, value in [('game_id', 'wrong'), ('home_team_id', '1610612752'),
                           ('home', 'NYK'), ('away_team_id', None)]:
            with self.subTest(key=key):
                source = sample()
                source['forecasts'][0][key] = value
                self.assertEqual(audit(source)['status'], 'invalid')

    def test_invalid_probabilities(self):
        for value in [True, '0.4', None, float('nan'), float('inf'), -.1, 1.1, 10**1000]:
            with self.subTest(value=str(value)[:20]):
                source = sample()
                source['forecasts'][0]['p_home_experimental'] = value
                self.assertEqual(audit(source)['status'], 'invalid')

    def test_sum_and_numeric_tolerance(self):
        source = sample()
        source['forecasts'][0]['p_away_experimental'] = .5
        self.assertEqual(audit(source)['status'], 'invalid')
        source['forecasts'][0]['p_away_experimental'] = .6000000000000001
        self.assertEqual(audit(source)['status'], 'formal_consistent')

    def test_generated_timestamp(self):
        for value in [None, 'bad', '2026-11-17T20:54:59']:
            source = dict(sample(), generated_at_utc=value)
            self.assertEqual(audit(source)['status'], 'invalid')

    def test_start_timestamp_and_pregame(self):
        for value in ['bad', '2026-11-18T00:30:00',
                      '2026-11-17T20:54:59+00:00', '2026-11-17T20:54:58+00:00']:
            source = sample()
            source['forecasts'][0]['start_time_utc'] = value
            self.assertEqual(audit(source)['status'], 'invalid')

    def test_timezone_comparison(self):
        source = dict(sample(), generated_at_utc='2026-11-18T01:00:00+02:00')
        self.assertEqual(audit(source)['status'], 'formal_consistent')

    def test_bad_row_does_not_hide_good_row(self):
        source = sample()
        source['forecasts'].append(None)
        self.assertEqual(audit(source)['consistent_count'], 1)
        self.assertEqual(audit(source)['status'], 'invalid')

    def test_cli_read_only_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'snapshot.json'
            for payload, expected in [(sample(), 0), (dict(sample(), forecasts=[]), 2), ({}, 1)]:
                text = json.dumps(payload)
                path.write_text(text, encoding='utf-8')
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main([str(path)]), expected)
                self.assertFalse(json.loads(output.getvalue())['betting_release'])
                self.assertEqual(path.read_text(encoding='utf-8'), text)
            path.write_text('{', encoding='utf-8')
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path)]), 1)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path.with_name('missing.json'))]), 1)


if __name__ == '__main__':
    unittest.main()
