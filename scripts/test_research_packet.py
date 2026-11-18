import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from types import SimpleNamespace
import numpy as np
import pandas as pd
from research_packet import team_summary, half_point_probability as probability, paper_price, build, enrich_latest, main


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'season': 2027, 'team_id': 'H', 'game_id': str(i),
                      'game_date': f'2026-11-{i:02d}', 'opp_team_id': 'A',
                      'pts': 100 + i, 'off_rating': 100 + i,
                      'def_rating': 90 + i, 'pace': 95} for i in range(1, 13)]

    def test_team_summary(self):
        r = team_summary(self.rows, 'H', 2027, '2026-11-13')
        self.assertEqual((r['season_games'], r['last10_games']), (12, 10))
        self.assertEqual(r['rest_days_uncapped'], 0)
        self.assertEqual(r['season_mean_per_game']['off_rating'], 106.5)
        self.assertEqual(r['last10_mean_per_game']['off_rating'], 107.5)

    def test_no_future_or_other_season_leakage(self):
        r = team_summary(self.rows + [dict(self.rows[0], season=2026)], 'H', 2027, '2026-11-05')
        self.assertEqual(r['season_games'], 4)
        self.assertEqual(r['latest_game_date'], '2026-11-04')
        r = team_summary(self.rows, 'H', 2027, '2026-12-01')
        self.assertGreater(r['rest_days_uncapped'], 7)
        self.assertEqual(r['rest_days_model_capped7'], 7)

    def test_invalid_team_data(self):
        for rows in [self.rows[:2], self.rows + [self.rows[0]],
                     [dict(r, pace=float('nan')) for r in self.rows]]:
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                team_summary(rows, 'H', 2027, '2026-11-13')

    def test_spread_sides_and_monotonicity(self):
        errors = [-10, 0, 10] * 100
        home = probability(3, errors, 'spread', 'home', -2.5)
        away = probability(3, errors, 'spread', 'away', 2.5)
        self.assertAlmostEqual(home + away, 1)
        self.assertAlmostEqual(home, 2 / 3)
        self.assertGreaterEqual(probability(3, errors, 'spread', 'home', 8.5), home)

    def test_totals_and_price(self):
        errors = [-10, 0, 10] * 100
        over = probability(220, errors, 'total', 'over', 220.5)
        under = probability(220, errors, 'total', 'under', 220.5)
        self.assertAlmostEqual(over + under, 1)
        r = paper_price(over, 2)
        self.assertAlmostEqual(r['paper_ev'], -1 / 3)
        self.assertFalse(r['betting_release'])

    def test_reject_unsupported_lines(self):
        for line in [2, 2.25, float('nan'), True]:
            with self.subTest(line=line), self.assertRaises(ValueError):
                probability(3, [0] * 200, 'spread', 'home', line)
        with self.assertRaises(ValueError):
            probability(3.5, [0] * 200, 'spread', 'home', -3.5)
        with self.assertRaises(ValueError):
            probability(3, [0], 'spread', 'home', -2.5)
        with self.assertRaises(ValueError):
            paper_price(.5, 1)

    def test_packet_integration_without_network(self):
        rows = self.rows + [dict(r, team_id='A', opp_team_id='H') for r in self.rows]
        date = pd.Timestamp('2026-11-13')
        f = {'game_id': 'future', 'home_team_id': 'H', 'away_team_id': 'A',
             'home': 'HOME', 'away': 'AWAY', 'start_time_utc': '2026-11-14T00:00:00Z',
             'home_margin_point': 3., 'total_point': 220.}
        ns = {'report': {'generated_at_utc': '2026-11-13T12:00:00Z', 'protocol': 'test',
                         'execution_ok': True, 'forecasts': [f],
                         'completed_schedule_games_missing_from_logs': []},
              'data': pd.DataFrame(rows), 'current': 2027,
              'upcoming': SimpleNamespace(itertuples=lambda: iter([
                  SimpleNamespace(game_id='future', home_team_id='H', away_team_id='A', game_date=date)])),
              'features': ['rest'], 'future_features': lambda team, date: [0],
              'residuals': np.zeros((200, 2))}
        packet, distribution = build(ns)
        self.assertTrue(packet['execution_ok'])
        self.assertFalse(packet['markets_linked'])
        self.assertEqual(packet['fixtures'][0]['home_context']['season_games'], 12)
        self.assertEqual(distribution['residual_n'], 200)
        self.assertFalse(distribution['betting_release'])
        before = json.dumps(ns['report'], sort_keys=True)
        enriched = enrich_latest(ns['report'], packet)
        self.assertEqual(enriched['forecasts'][0]['home_margin_point'], 3.)
        self.assertEqual(enriched['forecasts'][0]['home_context']['season_games'], 12)
        self.assertEqual(json.dumps(ns['report'], sort_keys=True), before)
        with self.assertRaises(ValueError):
            enrich_latest(dict(ns['report'], protocol='different'), packet)
        ns['report']['completed_schedule_games_missing_from_logs'] = ['missing']
        with self.assertRaises(ValueError):
            build(ns)

    def test_runner_calls_original_once(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                with patch('research_packet.runpy.run_path', return_value={'report': {}}) as run, patch(
                        'research_packet.build', return_value=({'execution_ok': True}, {'available': True})), patch(
                        'research_packet.enrich_latest', return_value={}):
                    main()
                    run.assert_called_once()
                self.assertTrue(json.loads(Path('reports/research_packet.json').read_text())['execution_ok'])
            finally:
                os.chdir(previous)

    def test_failure_clears_stale_distribution(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                Path('reports').mkdir()
                Path('reports/paper_distribution.json').write_text('{"available": true}')
                with patch('research_packet.runpy.run_path', side_effect=ValueError('source unavailable')):
                    main()
                self.assertFalse(json.loads(Path('reports/research_packet.json').read_text())['execution_ok'])
                self.assertFalse(json.loads(Path('reports/paper_distribution.json').read_text())['available'])
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
