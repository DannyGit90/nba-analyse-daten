import copy
import datetime as dt
import unittest
from check_paper_health import assess


class PaperHealthTests(unittest.TestCase):
    def test_status_cases(self):
        now = dt.datetime(2026, 11, 18, 12, tzinfo=dt.timezone.utc)
        p = {'protocol': 'test', 'generated_at_utc': '2026-11-18T11:00:00+00:00',
             'execution_ok': True, 'money_betting_released': False,
             'forecasts': [{'game_id': 'g'}], 'skipped_games': [],
             'completed_schedule_games_missing_from_logs': [], 'upcoming_schedule_games': 1}
        e = {'protocol': 'test', 'checked_at_utc': '2026-11-18T11:01:00+00:00',
             'execution_ok': True, 'betting_release': False}
        cases = [
            ({}, {}, 'ready_paper_only', True),
            ({'forecasts': [], 'skipped_games': [{'game_id': str(i)} for i in range(12)],
              'upcoming_schedule_games': 12,
              'completed_schedule_games_missing_from_logs': ['0022600257']}, {}, 'blocked_freshness', False),
            ({'forecasts': [], 'skipped_games': [{'game_id': 'g'}]}, {}, 'blocked_no_forecasts', False),
            ({'forecasts': [], 'upcoming_schedule_games': 0}, {}, 'no_upcoming_games', True),
            ({'skipped_games': [{'game_id': 'other'}], 'upcoming_schedule_games': 2}, {}, 'partial', True),
            ({'execution_ok': False}, {}, 'execution_error', False),
            ({}, {'execution_ok': False}, 'execution_error', False),
            ({'generated_at_utc': '2026-11-18T03:00:00+00:00'}, {}, 'stale_report', False),
            ({'generated_at_utc': '2026-11-18T13:00:00+00:00'}, {}, 'invalid_report', False),
            ({}, {'checked_at_utc': '2026-11-18T10:00:00+00:00'}, 'invalid_report', False),
            ({}, {'protocol': 'other'}, 'invalid_report', False),
            ({'skipped_games': [{'game_id': 'g'}], 'upcoming_schedule_games': 2}, {}, 'invalid_report', False),
            ({'upcoming_schedule_games': 2}, {}, 'invalid_report', False),
            ({'upcoming_schedule_games': True}, {}, 'invalid_report', False),
            ({'generated_at_utc': '2026-11-18T11:00:00'}, {}, 'invalid_report', False),
            ({'money_betting_released': True}, {}, 'invalid_report', False),
        ]
        for changes, evaluation, status, usable in cases:
            with self.subTest(changes=changes, evaluation=evaluation):
                a, b = copy.deepcopy(p), copy.deepcopy(e)
                a.update(changes)
                b.update(evaluation)
                before = copy.deepcopy(a)
                r = assess(a, b, now)
                self.assertEqual(r['status'], status)
                self.assertEqual(r['pipeline_usable'], usable)
                self.assertFalse(r['betting_release'])
                self.assertEqual(a, before)


if __name__ == '__main__':
    unittest.main()
