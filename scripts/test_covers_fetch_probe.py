"""Offline diagnosis classification tests, not live-import acceptance tests."""
import copy
import datetime as dt
import unittest
from covers_fetch_probe import select_fixture, summarize_espn, BASE


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 20, 11, tzinfo=dt.timezone.utc)
        self.f = {'game_id': '0022600043', 'home': 'ATL', 'away': 'CHA',
                  'start_time_utc': '2026-11-21T00:00:00Z'}
        self.paper = {'generated_at_utc': self.now.isoformat(), 'protocol': 'test', 'forecasts': [self.f]}
        self.url = 'https://www.covers.com/sport/basketball/nba/matchup/388223/odds'
        self.index = dict(self.paper, source_errors=[{'game_id': self.f['game_id'], 'source': self.url}])
        self.competition = {'date': self.f['start_time_utc'], 'status': {'type': {'state': 'pre'}},
            'competitors': [{'homeAway': 'home', 'team': {'abbreviation': 'ATL'}},
                            {'homeAway': 'away', 'team': {'abbreviation': 'CHA'}}]}

    def diagnose(self, competition):
        return summarize_espn({'events': [{'competitions': [competition]}]}, self.f, self.now)

    def test_selects_current_fixture_not_fixed_yesterday_url(self):
        self.assertEqual(select_fixture(self.paper, self.index, self.now), (self.f, self.url))

    def test_started_fixture_is_not_used(self):
        paper = dict(self.paper, forecasts=[dict(self.f, start_time_utc=self.now.isoformat())])
        with self.assertRaises(ValueError):
            select_fixture(paper, self.index, self.now)

    def test_mismatched_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            select_fixture(self.paper, dict(self.index, protocol='other'), self.now)

    def test_untrusted_or_unmatched_source_not_fetched(self):
        for error in [{'game_id': self.f['game_id'], 'source': 'https://example.org/odds'},
                      {'game_id': 'other', 'source': self.url}]:
            with self.subTest(error=error), self.assertRaises(ValueError):
                select_fixture(self.paper, dict(self.index, source_errors=[error]), self.now)

    def test_wrong_schema_distinct_from_empty_events(self):
        self.assertEqual(summarize_espn({}, self.f, self.now)['diagnosis'], 'unexpected_top_level_schema')
        self.assertEqual(summarize_espn({'events': []}, self.f, self.now)['diagnosis'], 'no_events')

    def test_no_team_match(self):
        c = copy.deepcopy(self.competition)
        c['competitors'][0]['team']['abbreviation'] = 'CLE'
        self.assertEqual(self.diagnose(c)['diagnosis'], 'no_team_match')

    def test_start_time_mismatch(self):
        c = dict(self.competition, date='2026-11-21T01:00:00Z')
        self.assertEqual(self.diagnose(c)['diagnosis'], 'start_time_mismatch')

    def test_not_pregame(self):
        c = dict(self.competition, status={'type': {'state': 'in'}})
        self.assertEqual(self.diagnose(c)['diagnosis'], 'not_pregame')

    def test_absent_and_empty_odds_identified(self):
        for c in [self.competition, dict(self.competition, odds=[])]:
            self.assertEqual(self.diagnose(c)['diagnosis'], 'no_expected_odds_blocks')

    def test_odds_blocks_identified_without_accepting_prices(self):
        c = dict(self.competition, odds=[{'provider': {'name': 'Example'}, 'details': 'ATL -6.5'}])
        result = self.diagnose(c)
        self.assertEqual(result['odds_blocks'], 1)
        self.assertEqual(result['diagnosis'], 'odds_blocks_present_check_collector_output')
        self.assertNotIn('p_experimental', result)

    def test_samples_bounded(self):
        c = dict(self.competition, odds=[{'x': 'a' * 10000}])
        result = summarize_espn({'events': [{'competitions': [c] * 10}]}, self.f, self.now)
        self.assertEqual(len(result['samples']), 2)
        self.assertLessEqual(len(result['samples'][0]['odds_sample_json']), 1500)


if __name__ == '__main__':
    unittest.main()
