import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from daily_review import american, collect, score, publish


class DailyReviewTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 18, 16, tzinfo=dt.timezone.utc)
        self.paper = {'protocol': 'test', 'generated_at_utc': '2026-11-18T15:00:00+00:00',
                      'execution_ok': True, 'money_betting_released': False,
                      'completed_schedule_games_missing_from_logs': [], 'forecasts': []}
        ctx = {'season_games': 14, 'last10_games': 10, 'rest_days_uncapped': 1,
               'season_mean_per_game': {'off_rating': 115., 'def_rating': 110., 'pace': 99.},
               'last10_mean_per_game': {'off_rating': 116., 'def_rating': 111., 'pace': 100.},
               'recent_games': [{'game_id': str(j), 'points': 110, 'opponent_id': 'team'} for j in range(10)]}
        self.packet = {'protocol': 'test', 'generated_at_utc': self.paper['generated_at_utc'],
                       'execution_ok': True, 'fixtures': []}
        self.events = []
        for i in range(12):
            start = (dt.datetime(2026, 11, 19, tzinfo=dt.timezone.utc) + dt.timedelta(minutes=i * 15)).isoformat()
            gid = f'002260{258 + i:04d}'
            f = {'game_id': gid, 'home': 'DEN', 'away': 'BOS', 'start_time_utc': start,
                 'p_home_experimental': .6, 'p_away_experimental': .4,
                 'home_margin_point': 3., 'total_point': 220.,
                 'home_context': copy.deepcopy(ctx), 'away_context': copy.deepcopy(ctx)}
            self.paper['forecasts'].append(f)
            self.packet['fixtures'].append(copy.deepcopy(f))
            self.events.append({'date': start, 'status': {'type': {'state': 'pre'}},
                'competitions': [{'date': start, 'competitors': [
                    {'homeAway': 'home', 'team': {'abbreviation': 'DEN'}},
                    {'homeAway': 'away', 'team': {'abbreviation': 'BOS'}}],
                    'odds': [{'provider': {'name': 'Example Book'}, 'details': 'DEN -2.5',
                              'homeTeamOdds': {'moneyLine': -150, 'spreadOdds': -110},
                              'awayTeamOdds': {'moneyLine': 130, 'spreadOdds': -110},
                              'overUnder': 220.5, 'overOdds': -110, 'underOdds': -110}]}]})
        self.d = {'protocol': 'test', 'generated_at_utc': self.paper['generated_at_utc'],
                  'available': True, 'margin_residuals': [-10, 0, 10] * 100,
                  'total_residuals': [-10, 0, 10] * 100}

    def offers(self):
        return collect(self.paper, self.now, lambda url: {'events': self.events})[0]

    def test_complete_twelve_game_fixture(self):
        before = copy.deepcopy(self.paper)
        offers = self.offers()
        self.assertEqual(len(offers), 72)
        rows = score(self.paper, self.d, offers, self.now)
        self.assertTrue(all(r['calculation_status'] == 'computed_reference_only' for r in rows))
        self.assertTrue(all(r['recommendation'] is None and r['betting_release'] is False for r in rows))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'paper_log').mkdir()
            (root / 'paper_log/keep.json').write_text('preserved')
            index = publish(self.paper, self.packet, rows, [], root)
            self.assertEqual((index['actual_offer_count'], index['computed_offer_count']), (72, 72))
            self.assertEqual(len(index['fixtures']), 12)
            for p in root.rglob('*.json'):
                if p.name != 'keep.json':
                    self.assertLessEqual(p.stat().st_size, 16000 if p.name == 'paper_latest.json' else 10000)
            slim = json.loads((root / 'paper_latest.json').read_text())
            self.assertEqual(len(slim['forecasts']), 12)
            self.assertNotIn('home_context', slim['forecasts'][0])
            self.assertIn('home_summary', slim['forecasts'][11])
            self.assertEqual((root / 'paper_log/keep.json').read_text(), 'preserved')
        self.assertEqual(self.paper, before)

    def test_missing_prices_are_not_invented(self):
        for e in self.events:
            e['competitions'][0]['odds'][0] = {'provider': {'name': 'Example Book'}, 'details': 'DEN -2.5', 'overUnder': 220.5}
        self.assertEqual(self.offers(), [])

    def test_missing_provider_is_not_invented(self):
        for e in self.events:
            e['competitions'][0]['odds'][0].pop('provider')
        self.assertEqual(self.offers(), [])

    def test_source_failure_is_visible(self):
        def fail(url):
            raise OSError('unavailable')
        offers, errors = collect(self.paper, self.now, fail)
        self.assertEqual(offers, [])
        self.assertTrue(errors)

    def test_started_and_mismatched_games_excluded(self):
        for e in self.events:
            e['status']['type']['state'] = 'in'
        self.assertEqual(self.offers(), [])
        for e in self.events:
            e['status']['type']['state'] = 'pre'
            e['competitions'][0]['competitors'][0]['team']['abbreviation'] = 'OTHER'
        self.assertEqual(self.offers(), [])

    def test_distribution_mismatch_only_blocks_spread_total(self):
        d = dict(self.d, protocol='wrong')
        rows = score(self.paper, d, self.offers(), self.now)
        self.assertEqual(sum(r['calculation_status'] == 'computed_reference_only' for r in rows), 24)

    def test_stale_inputs_and_unsupported_lines(self):
        offers = self.offers()
        offers[0]['observed_at_utc'] = '2026-11-18T10:00:00Z'
        self.assertEqual(score(self.paper, self.d, offers[:1], self.now)[0]['calculation_status'], 'not_computed')
        spread = next(o for o in offers if o['market'] == 'spread')
        spread['line'] = 2
        self.assertEqual(score(self.paper, self.d, [spread], self.now)[0]['calculation_status'], 'not_computed')

    def test_snapshot_and_file_size_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                publish(self.paper, dict(self.packet, protocol='wrong'), [], [], Path(tmp))
            packet = copy.deepcopy(self.packet)
            packet['fixtures'][0]['oversized'] = 'x' * 11000
            with self.assertRaises(ValueError):
                publish(self.paper, packet, [], [], Path(tmp))
            self.assertFalse((Path(tmp) / 'paper_latest.json').exists())

    def test_integer_push_blockers_are_explicit(self):
        for market in ('total', 'spread'):
            offer = next(o for o in self.offers() if o['market'] == market)
            offer['line'] = 220 if market == 'total' else 2
            before = copy.deepcopy(offer)
            row = score(self.paper, self.d, [offer], self.now)[0]
            self.assertEqual(row['calculation_status'], 'not_computed')
            self.assertIn('push_integration_pending', row['push_blockers'])
            self.assertIn('settlement_rules_unverified', row['push_blockers'])
            self.assertEqual('discrete_margin_model_not_integrated' in row['push_blockers'], market == 'spread')
            self.assertTrue(row['reason'].startswith('Integer-line push blocked: '))
            self.assertNotIn('p_experimental', row)
            self.assertNotIn('paper_ev', row)
            self.assertFalse(row['betting_release'])
            self.assertIsNone(row['recommendation'])
            self.assertEqual(offer, before)

    def test_rule_flag_alone_does_not_enable_push(self):
        offer = next(o for o in self.offers() if o['market'] == 'total')
        offer.update(line=220, rules_verified=True)
        row = score(self.paper, self.d, [offer], self.now)[0]
        self.assertEqual(row['calculation_status'], 'not_computed')
        self.assertEqual(row['push_blockers'], ['push_integration_pending', 'rule_to_offer_binding_pending'])
        self.assertNotIn('p_experimental', row)

    def test_other_failures_are_not_replaced_by_push_diagnostics(self):
        base = next(o for o in self.offers() if o['market'] == 'total')
        cases = [(dict(base, line=220.25), self.d),
                 (dict(base, line=220, observed_at_utc='2026-11-18T10:00:00Z'), self.d),
                 (dict(base, line=220), dict(self.d, protocol='wrong')),
                 (dict(base, line=220), dict(self.d, total_residuals=[0] * 10)),
                 (dict(base, line=220, side='invalid'), self.d),
                 (dict(base, line=-220), self.d), (dict(base, line=True), self.d)]
        for offer, distribution in cases:
            with self.subTest(offer=offer):
                row = score(self.paper, distribution, [offer], self.now)[0]
                self.assertEqual(row['calculation_status'], 'not_computed')
                self.assertNotIn('push_blockers', row)
                self.assertFalse(row['reason'].startswith('Integer-line push blocked: '))

    def test_integer_blockers_survive_report_publication(self):
        offers = self.offers()
        for offer in offers:
            if offer['market'] == 'total':
                offer['line'] = 220
        rows = score(self.paper, self.d, offers, self.now)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = publish(self.paper, self.packet, rows, [], root)
            self.assertEqual((index['actual_offer_count'], index['computed_offer_count']), (72, 48))
            blocked = []
            for fixture in index['fixtures']:
                context = json.loads((root / fixture['context_path'].removeprefix('reports/')).read_text())
                for page in context['market_pages']:
                    content = json.loads((root / page.removeprefix('reports/')).read_text())
                    blocked.extend(r for r in content['offers'] if r['market'] == 'total')
            self.assertEqual(len(blocked), 24)
            self.assertTrue(all('settlement_rules_unverified' in r['push_blockers'] for r in blocked))

    def test_american_conversion(self):
        self.assertAlmostEqual(american(-110), 1 + 100 / 110)
        self.assertEqual(american(150), 2.5)
        for x in [None, 0, 99, float('nan'), True]:
            with self.subTest(x=x), self.assertRaises((ValueError, TypeError)):
                american(x)


if __name__ == '__main__':
    unittest.main()
