"""Synthetic schema regressions; observed nested home path reproduced, not a saved full response."""
import copy
import datetime as dt
import unittest
from daily_review import collect


class EspnSchemaTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 20, 12, tzinfo=dt.timezone.utc)
        self.f = {'game_id': '0022600043', 'home': 'ATL', 'away': 'CHA',
                  'start_time_utc': '2026-11-21T00:00:00Z'}
        self.paper = {'forecasts': [self.f]}
        self.block = {'provider': {'name': 'DraftKings'},
                      'moneyline': {'home': {'close': {'odds': '-230'}}}}

    def collect_block(self, block, state='pre', start=None, home='ATL'):
        date = start or self.f['start_time_utc']
        payload = {'events': [{'date': date, 'status': {'type': {'state': state}},
            'competitions': [{'date': date, 'competitors': [
                {'homeAway': 'home', 'team': {'abbreviation': home}},
                {'homeAway': 'away', 'team': {'abbreviation': 'CHA'}}], 'odds': [block]}]}]}
        return collect(self.paper, self.now, lambda url: payload)

    def test_observed_nested_home_field_imported(self):
        rows, errors = self.collect_block(self.block)
        self.assertEqual((len(rows), errors), (1, []))
        self.assertEqual((rows[0]['market'], rows[0]['side'], rows[0]['line']), ('moneyline', 'home', None))
        self.assertAlmostEqual(rows[0]['odds'], 1 + 100 / 230)
        self.assertEqual(rows[0]['price_field'], 'moneyline.home.close.odds')

    def test_synthetic_away_price_assigned_to_away(self):
        b = copy.deepcopy(self.block)
        b['moneyline']['away'] = {'close': {'odds': '+191'}}
        rows, errors = self.collect_block(b)
        self.assertEqual(len(rows), 2)
        self.assertEqual(errors, [])
        self.assertAlmostEqual(next(r for r in rows if r['side'] == 'away')['odds'], 2.91)

    def test_open_only_is_not_imported(self):
        b = copy.deepcopy(self.block)
        b['moneyline']['home'] = {'open': {'odds': '-200'}}
        rows, errors = self.collect_block(b)
        self.assertEqual(rows, [])
        self.assertTrue(any('no supported' in e['error'] for e in errors))

    def test_open_not_selected_over_close(self):
        b = copy.deepcopy(self.block)
        b['moneyline']['home']['open'] = {'odds': '-200'}
        self.assertAlmostEqual(self.collect_block(b)[0][0]['odds'], 1 + 100 / 230)

    def test_legacy_six_markets_unchanged(self):
        b = {'provider': {'name': 'DraftKings'}, 'details': 'ATL -6.5',
             'homeTeamOdds': {'moneyLine': -230, 'spreadOdds': -110},
             'awayTeamOdds': {'moneyLine': 191, 'spreadOdds': -110},
             'overUnder': 219.5, 'overOdds': -105, 'underOdds': -115}
        rows, errors = self.collect_block(b)
        self.assertEqual((len(rows), errors), (6, []))
        self.assertEqual({(r['market'], r['side']) for r in rows},
            {('moneyline','home'),('moneyline','away'),('spread','home'),('spread','away'),('total','over'),('total','under')})
        self.assertTrue(all('price_field' not in r for r in rows))

    def test_conflicting_formats_reject_only_affected_side(self):
        b = copy.deepcopy(self.block)
        b['homeTeamOdds'] = {'moneyLine': -150}
        b['awayTeamOdds'] = {'moneyLine': 191}
        rows, errors = self.collect_block(b)
        self.assertEqual([r['side'] for r in rows], ['away'])
        self.assertTrue(any('Conflicting' in e['error'] for e in errors))

    def test_equal_formats_produce_one_price(self):
        b = dict(self.block, homeTeamOdds={'moneyLine': -230})
        rows, errors = self.collect_block(b)
        self.assertEqual((len(rows), errors), (1, []))

    def test_bad_nested_prices_not_replaced_by_open(self):
        for value in [True, 0, 99, 'nan', '56%', {}, 'bad']:
            b = copy.deepcopy(self.block)
            b['moneyline']['home'] = {'close': {'odds': value}, 'open': {'odds': '-200'}}
            with self.subTest(value=value):
                rows, errors = self.collect_block(b)
                self.assertEqual(rows, [])
                self.assertTrue(errors)

    def test_malformed_nested_objects_not_accepted(self):
        for value in [None, [], 'bad']:
            b = dict(self.block, moneyline=value)
            with self.subTest(value=value):
                rows, errors = self.collect_block(b)
                self.assertEqual(rows, [])
                self.assertTrue(errors)

    def test_safety_and_freshness_flags_unchanged(self):
        row = self.collect_block(self.block)[0][0]
        self.assertFalse(row['betting_release'])
        self.assertFalse(row['rules_verified'])
        self.assertIsNone(row['price_timestamp_utc'])
        self.assertEqual(row['price_status'], 'indirect_reference_time_unknown')

    def test_game_and_pregame_guards_preserved(self):
        for args in [{'state': 'in'}, {'home': 'CLE'}, {'start': '2026-11-21T01:00:00Z'}]:
            with self.subTest(args=args):
                self.assertEqual(self.collect_block(self.block, **args)[0], [])

    def test_missing_provider_not_invented(self):
        b = dict(self.block)
        b.pop('provider')
        self.assertEqual(self.collect_block(b)[0], [])

    def test_input_not_mutated(self):
        before = copy.deepcopy(self.block)
        self.collect_block(self.block)
        self.assertEqual(self.block, before)

    def test_diagnostics_bounded(self):
        events = []
        for i in range(100):
            events.append({'date': self.f['start_time_utc'], 'status': {'type': {'state': 'pre'}},
                'competitions': [{'date': self.f['start_time_utc'], 'competitors': [
                    {'homeAway':'home','team':{'abbreviation':'ATL'}},
                    {'homeAway':'away','team':{'abbreviation':'CHA'}}],
                    'odds':[{'provider':{'name':'x' * 1000}, 'moneyline':{}}]}]})
        rows, errors = collect(self.paper, self.now, lambda url: {'events': events})
        self.assertEqual(rows, [])
        self.assertTrue(any(e.get('omitted_count', 0) > 0 for e in errors))
        import json
        self.assertLess(len(json.dumps(errors).encode()), 2200)


if __name__ == '__main__':
    unittest.main()
