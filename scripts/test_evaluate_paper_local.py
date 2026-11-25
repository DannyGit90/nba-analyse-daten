"""Synthetic tests for local-result evaluation; no real data and no betting release."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'evaluate_paper.py'
START = '2019-11-18T00:30:00+00:00'


def forecast(gid='0022600001', p=0.7, home_id='1610612761', away_id='1610612752', **changes):
    row = {'game_id': gid, 'start_time_utc': START, 'home_team_id': home_id, 'away_team_id': away_id,
           'home': 'TOR', 'away': 'NYK', 'p_home_experimental': p, 'p_away_experimental': 1 - p,
           'home_margin_point': 4.0, 'total_point': 220.0, 'margin_interval80': [-10.0, 18.0],
           'total_interval80': [195.0, 245.0], 'baseline_home_probability': 0.55, 'betting_release': False}
    row.update(changes)
    return row


def snapshot(generated='2019-11-17T20:00:00+00:00', forecasts=None, **changes):
    data = {'protocol': 'season-prior10-paper-v1', 'execution_ok': True, 'generated_at_utc': generated,
            'forecasts': [forecast()] if forecasts is None else forecasts}
    data.update(changes)
    return data


def log_rows(gid='0022600001', home_pts=110, away_pts=100, home_id='1610612761', away_id='1610612752'):
    return [{'game_id': gid, 'team_id': home_id, 'opp_team_id': away_id, 'home': True, 'pts': home_pts},
            {'game_id': gid, 'team_id': away_id, 'opp_team_id': home_id, 'home': False, 'pts': away_pts}]


class LocalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'paper_log').mkdir()

    def archive(self, name, data):
        (self.root / 'paper_log' / name).write_text(json.dumps(data), encoding='utf-8')

    def logs(self, rows, season=2020):
        folder = self.root / 'data' / 'nba' / 'team_game_logs'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ('season=' + str(season) + '.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')

    def run_script(self):
        done = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads((self.root / 'reports' / 'paper_evaluation.json').read_text())

    def test_scores_from_local_logs_only(self):
        self.archive('a.json', snapshot())
        self.logs(log_rows() + log_rows('0022600999', 90, 95))
        result = self.run_script()
        self.assertTrue(result['execution_ok'])
        self.assertEqual(result['results_source'], 'local:nba-source-store')
        self.assertEqual(result['results_source_files'], ['data/nba/team_game_logs/season=2020.jsonl'])
        self.assertEqual(result['results_rows_read'], 4)
        self.assertEqual((result['unique_games_archived'], result['games_scored'], result['games_waiting_for_results']), (1, 1, 0))
        self.assertAlmostEqual(result['metrics']['model_brier'], 0.09)
        self.assertAlmostEqual(result['metrics']['baseline_brier'], 0.2025)
        self.assertEqual(result['metrics']['margin_abs_error'], 6.0)
        self.assertEqual(result['metrics']['total_abs_error'], 10.0)
        self.assertFalse(result['betting_release'])

    def test_missing_results_wait_and_dynamic_update(self):
        self.archive('a.json', snapshot())
        self.logs([])
        self.assertEqual(self.run_script()['games_waiting_for_results'], 1)
        self.logs(log_rows())
        self.assertEqual(self.run_script()['games_scored'], 1)

    def test_new_archive_game_is_picked_up_and_earliest_forecast_is_used(self):
        self.archive('a.json', snapshot('2019-11-17T18:00:00+00:00', [forecast(p=0.7)]))
        self.archive('b.json', snapshot('2019-11-17T19:00:00+00:00', [forecast(p=0.2), forecast('0022600002', p=0.4)]))
        self.logs(log_rows() + log_rows('0022600002', 100, 101))
        result = self.run_script()
        self.assertEqual((result['unique_games_archived'], result['games_scored']), (2, 2))
        self.assertAlmostEqual(result['metrics']['model_brier'], (0.09 + 0.16) / 2)

    def test_invalid_pairs_are_reported_not_scored(self):
        self.archive('a.json', snapshot(forecasts=[forecast('0022600001'), forecast('0022600002'), forecast('0022600003')]))
        rows = log_rows('0022600001', 100, 100) + log_rows('0022600002')[:1]
        broken = log_rows('0022600003')
        broken[0]['home'] = None
        self.logs(rows + broken)
        result = self.run_script()
        self.assertEqual(result['games_scored'], 0)
        self.assertEqual(sorted(x['game_id'] for x in result['invalid_result_pairs']), ['0022600001', '0022600002', '0022600003'])

    def test_missing_season_file_fails_loudly_and_writes_report(self):
        self.archive('a.json', snapshot())
        result = self.run_script()
        self.assertFalse(result['execution_ok'])
        self.assertEqual(result['error_type'], 'FileNotFoundError')
        self.assertFalse(result['betting_release'])

    def test_malformed_local_row_fails_loudly(self):
        self.archive('a.json', snapshot())
        self.logs([{'team_id': '1'}])
        self.assertFalse(self.run_script()['execution_ok'])

    def test_after_start_archive_is_not_used_and_empty_archive_is_ok(self):
        self.archive('late.json', snapshot('2019-11-18T01:00:00+00:00'))
        self.logs(log_rows())
        result = self.run_script()
        self.assertTrue(result['execution_ok'])
        self.assertEqual(result['unique_games_archived'], 0)
        self.assertEqual(result['results_source_files'], [])

    def test_inputs_unchanged_and_no_remote_dependency(self):
        self.archive('a.json', snapshot())
        self.logs(log_rows())
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.run_script()
        after = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and 'reports' not in p.parts}
        self.assertEqual(before, after)
        self.assertNotIn('duckdb', SCRIPT.read_text(encoding='utf-8'))
        self.assertNotIn('http', SCRIPT.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
