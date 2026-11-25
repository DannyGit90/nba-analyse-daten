"""Synthetic result-matching tests; not actual NBA results."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from winner_outcome_audit import match, main


def sample():
    forecast = {'game_id': '0022600253', 'start_time_utc': '2026-11-18T00:30:00+00:00',
                'home_team_id': '1610612761', 'away_team_id': '1610612752',
                'home': 'TOR', 'away': 'NYK', 'p_home_experimental': .4, 'p_away_experimental': .6}
    snapshot = {'protocol': 'season-prior10-paper-v1', 'execution_ok': True,
                'generated_at_utc': '2026-11-17T20:00:00+00:00', 'forecasts': [forecast]}
    fixture = dict(forecast, start_time=forecast['start_time_utc'], status='final', game_date='2026-11-17')
    logs = [{'game_id': forecast['game_id'], 'team_id': forecast[side + '_team_id'],
             'opp_team_id': forecast[other + '_team_id'], 'home': side == 'home',
             'pts': score, 'game_date': '2026-11-17'}
            for side, other, score in [('home', 'away', 110), ('away', 'home', 100)]]
    return snapshot, logs, [fixture]


class OutcomeTests(unittest.TestCase):
    def run_match(self, inputs):
        return match(*inputs, as_of='2026-11-25T12:45:00+00:00')

    def test_match_and_no_mutation(self):
        inputs = sample()
        before = copy.deepcopy(inputs)
        result = self.run_match(inputs)
        self.assertEqual(result['matched_count'], 1)
        self.assertEqual(result['forecasts'][0]['winner'], 'home')
        self.assertEqual(inputs, before)
        self.assertFalse(result['betting_release'])
        self.assertEqual(result['probability_validation'], 'not_assessed')

    def test_away_winner_and_row_order(self):
        inputs = sample()
        inputs[1][1]['pts'] = 120
        inputs[1].reverse()
        self.assertEqual(self.run_match(inputs)['forecasts'][0]['winner'], 'away')

    def test_missing_duplicate_or_wrong_result(self):
        for change in ['missing', 'duplicate', 'swapped', 'opponent', 'flag', 'date', 'game_id']:
            with self.subTest(change=change):
                inputs = sample()
                if change == 'missing': inputs[1].pop()
                elif change == 'duplicate': inputs[1].append(copy.deepcopy(inputs[1][0]))
                else:
                    key, value = {'swapped': ('team_id', '1610612752'), 'opponent': ('opp_team_id', 'other'),
                                  'flag': ('home', 1), 'date': ('game_date', '2026-11-16'),
                                  'game_id': ('game_id', '0022600999')}[change]
                    inputs[1][0][key] = value
                self.assertEqual(self.run_match(inputs)['matched_count'], 0)

    def test_invalid_points_and_tie(self):
        for value in [None, True, '110', -1, 1.5, float('nan'), float('inf'), 10**1000, 100]:
            with self.subTest(value=str(value)[:20]):
                inputs = sample()
                inputs[1][0]['pts'] = value
                self.assertEqual(self.run_match(inputs)['matched_count'], 0)

    def test_schedule_identity_final_and_time(self):
        for key, value in [('home_team_id', 'wrong'), ('status', 'live'),
                           ('start_time', '2026-11-18T01:30:00+00:00'), ('start_time', None)]:
            inputs = sample()
            inputs[2][0][key] = value
            self.assertEqual(self.run_match(inputs)['matched_count'], 0)
        for change in ['missing', 'duplicate']:
            inputs = sample()
            if change == 'missing': inputs[2].clear()
            else: inputs[2].append(copy.deepcopy(inputs[2][0]))
            self.assertEqual(self.run_match(inputs)['matched_count'], 0)

    def test_future_and_naive_as_of(self):
        self.assertEqual(match(*sample(), as_of='2026-11-17T23:00:00+00:00')['matched_count'], 0)
        with self.assertRaises(ValueError):
            match(*sample(), as_of='2026-11-25T12:45:00')

    def test_formal_failure_and_empty(self):
        inputs = sample()
        inputs[0]['protocol'] = 'wrong'
        self.assertEqual(self.run_match(inputs)['status'], 'invalid_snapshot')
        inputs = sample()
        inputs[0]['forecasts'] = []
        self.assertEqual(self.run_match(inputs)['status'], 'no_forecasts')
        inputs[0]['forecasts'] = None
        self.assertEqual(self.run_match(inputs)['status'], 'invalid_snapshot')

    def test_local_failure_does_not_hide_match(self):
        inputs = sample()
        extra = copy.deepcopy(inputs[0]['forecasts'][0])
        extra['game_id'] = '0022600254'
        inputs[0]['forecasts'].append(extra)
        result = self.run_match(inputs)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['matched_count'], 1)

    def test_cli_existing_jsonl_and_read_only(self):
        snapshot, logs, schedule = sample()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'snapshot.json'
            source.write_text(json.dumps(snapshot), encoding='utf-8')
            for name, rows in [('team_game_logs', logs), ('schedule', schedule)]:
                (root / name).mkdir()
                (root / name / 'season=2027.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([str(source), '--data-root', str(root), '--as-of', '2026-11-25T12:45:00Z']), 0)
            self.assertEqual(json.loads(output.getvalue())['matched_count'], 1)
            self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()})
            snapshot['forecasts'].append(None)
            source.write_text(json.dumps(snapshot), encoding='utf-8')
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([str(source), '--data-root', str(root)]), 1)
            partial = json.loads(output.getvalue())
            self.assertEqual(partial['status'], 'partial')
            self.assertEqual(partial['matched_count'], 1)
            (root / 'schedule' / 'season=2027.jsonl').write_text('{', encoding='utf-8')
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([str(source), '--data-root', str(root)]), 1)
            self.assertEqual(json.loads(output.getvalue())['status'], 'source_error')


if __name__ == '__main__':
    unittest.main()
