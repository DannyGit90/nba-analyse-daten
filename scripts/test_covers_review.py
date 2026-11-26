import datetime as dt
import unittest
import json
from covers_review import Document, parse, collect


class CoversTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 18, 17, tzinfo=dt.timezone.utc)
        self.f = {'game_id': '0022600266', 'home': 'DEN', 'away': 'BOS',
                  'start_time_utc': '2026-11-19T02:30:00Z'}
        self.url = 'https://www.covers.com/sport/basketball/nba/matchup/388752/odds'
        self.html = '<title>Celtics vs Nuggets Odds For November 18, 2026</title>'
        for market, columns, values in [
                ('Spread', ('BOS', 'DEN'), ('-2.5 -106', '+2.5 -114')),
                ('Total', ('OVER', 'UNDER'), ('o220.5 -110', 'u220.5 -110')),
                ('Moneyline', ('BOS', 'DEN'), ('-148', '+126'))]:
            self.html += f'<h2>{market}</h2><h2>Odds Comparison</h2><table><tr><th>ALL BOOKS</th><th>{columns[0]}</th><th>{columns[1]}</th></tr>'
            self.html += f'<tr><td><img alt="FanDuel logo"></td><td>{values[0]}</td><td>{values[1]}</td></tr></table>'

    def test_source_derived_reference_values(self):
        rows, rejected = parse(self.html, self.f, self.url, self.now)
        self.assertEqual((len(rows), rejected), (6, 0))
        away_spread = next(r for r in rows if r['market'] == 'spread' and r['side'] == 'away')
        self.assertEqual((away_spread['line'], away_spread['bookmaker']), (-2.5, 'FanDuel'))
        self.assertAlmostEqual(away_spread['odds'], 1 + 100 / 106)
        self.assertTrue(all(r['price_timestamp_utc'] is None and r['rules_verified'] is False for r in rows))

    def test_player_props_are_not_game_totals(self):
        extra = '<h2>Points Scored</h2><table><tr><th>ALL BOOKS</th><th>OVER</th><th>UNDER</th></tr><tr><td>FanDuel logo</td><td>o25.5 -110</td><td>u25.5 -110</td></tr></table>'
        self.assertEqual(len(parse(self.html + extra, self.f, self.url, self.now)[0]), 6)

    def test_date_and_team_mismatch_rejected(self):
        for f in [dict(self.f, home='CLE'), dict(self.f, start_time_utc='2026-11-20T02:30:00Z')]:
            with self.subTest(f=f), self.assertRaises(ValueError):
                parse(self.html, f, self.url, self.now)

    def test_reversed_columns(self):
        text = self.html.replace('<th>BOS</th><th>DEN</th>', '<th>DEN</th><th>BOS</th>')
        rows = parse(text, self.f, self.url, self.now)[0]
        self.assertEqual(next(r for r in rows if r['market'] == 'spread' and r['side'] == 'home')['line'], -2.5)

    def test_missing_and_bad_prices_not_invented(self):
        text = self.html.replace('-148', '-').replace('+126', 'bad')
        rows, rejected = parse(text, self.f, self.url, self.now)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rejected, 1)

    def test_discovery_without_manual_daily_map(self):
        doc = Document()
        doc.feed('<a href="/sport/basketball/nba/matchup/388752">game</a>')
        self.assertIn(self.url, doc.links)

    def test_collector_deduplicates(self):
        def loader(url):
            return '<a href="/sport/basketball/nba/matchup/388752/odds">game</a>' if url.endswith('/nba/odds') else self.html
        rows, errors = collect({'forecasts': [self.f]}, self.now, loader)
        self.assertEqual(len(rows), 6)
        self.assertEqual(errors, [])

    def test_only_discovered_pages_are_fetched(self):
        requested = []
        def loader(url):
            requested.append(url)
            return '<a href="/sport/basketball/nba/matchup/388752/odds">game</a>' if url.endswith('/nba/odds') else self.html
        collect({'forecasts': [self.f]}, self.now, loader)
        self.assertEqual(requested, ['https://www.covers.com/sport/basketball/nba/odds', self.url])

    def test_source_failure_exposed(self):
        def loader(url):
            raise OSError('unavailable')
        rows, errors = collect({'forecasts': [self.f]}, self.now, loader)
        self.assertEqual(rows, [])
        self.assertTrue(any('No valid' in str(e) for e in errors))


class CoversDiagnosticTests(unittest.TestCase):
    """Synthetic HTML, not a saved Covers response or live-fix proof."""
    def setUp(self):
        self.now = dt.datetime(2026, 11, 19, 12, tzinfo=dt.timezone.utc)
        self.f = {'game_id': '0022600272', 'home': 'MIN', 'away': 'NYK',
                  'start_time_utc': '2026-11-20T01:00:00Z'}
        self.url = 'https://www.covers.com/sport/basketball/nba/matchup/388756/odds'
        self.html = '<title>Knicks vs Timberwolves Odds For November 19, 2026</title>'
        for market, columns, values in [
                ('Spread', ('NY', 'MIN'), ('-1.5 -110', '+1.5 -110')),
                ('Total', ('OVER', 'UNDER'), ('o217.5 -107', 'u217.5 -113')),
                ('Moneyline', ('NY', 'MIN'), ('-119', '+100'))]:
            self.html += f'<h2>{market}</h2><h2>Odds Comparison</h2><table><tr><th>ALL BOOKS</th><th>{columns[0]}</th><th>{columns[1]}</th></tr>'
            self.html += f'<tr><td><img alt="DraftKings logo"></td><td>{values[0]}</td><td>{values[1]}</td></tr></table>'

    def test_reference_numbers_and_flags_unchanged(self):
        samples = []
        rows, rejected = parse(self.html, self.f, self.url, self.now, samples)
        self.assertEqual((len(rows), rejected, samples), (6, 0, []))
        offer = next(r for r in rows if r['market'] == 'spread' and r['side'] == 'home')
        self.assertEqual((offer['line'], offer['bookmaker']), (1.5, 'DraftKings'))
        self.assertAlmostEqual(offer['odds'], 1 + 100 / 110)
        self.assertTrue(all(r['rules_verified'] is False and r['betting_release'] is False
                            and r['price_timestamp_utc'] is None for r in rows))

    def test_bad_format_is_logged_not_accepted(self):
        samples = []
        rows, rejected = parse(self.html.replace('+1.5 -110', '+1.5 - 110'), self.f, self.url, self.now, samples)
        self.assertEqual((len(rows), rejected), (5, 1))
        self.assertEqual(samples[0]['reason'], 'cell_format_mismatch')
        self.assertEqual(samples[0]['cell_text_repr'], "'+1.5 - 110'")

    def test_invisible_text_is_visible_in_diagnostics(self):
        samples = []
        text = self.html.replace('+100', '+100&#8203;')
        parse(text, self.f, self.url, self.now, samples)
        self.assertIn('\\u200b', samples[0]['cell_text_repr'])

    def test_invalid_american_price_is_logged(self):
        samples = []
        rows, rejected = parse(self.html.replace('+100', '+90'), self.f, self.url, self.now, samples)
        self.assertEqual((len(rows), rejected), (5, 1))
        self.assertEqual(samples[0]['reason'], 'invalid_american_price')

    def test_wrong_total_prefix_is_logged(self):
        samples = []
        rows, rejected = parse(self.html.replace('o217.5 -107', 'u217.5 -107'), self.f, self.url, self.now, samples)
        self.assertEqual((len(rows), rejected), (5, 1))
        self.assertEqual(samples[0]['reason'], 'total_side_prefix_mismatch')

    def test_42_synthetic_rejections_keep_count_and_bound_samples(self):
        samples = []
        text = self.html
        for value in ('-1.5 -110', '+1.5 -110', 'o217.5 -107', 'u217.5 -113', '-119', '+100'):
            text = text.replace('>' + value + '<', '>invalid<')
        row = '<tr><td>Other logo</td><td>invalid</td><td>invalid</td></tr>'
        text = text.replace('</table>', row * 6 + '</table>')
        rows, rejected = parse(text, self.f, self.url, self.now, samples)
        self.assertEqual((len(rows), rejected, len(samples)), (0, 42, 6))
        self.assertEqual({m: sum(s['market'] == m for s in samples) for m in ('spread', 'total', 'moneyline')},
                         {'spread': 2, 'total': 2, 'moneyline': 2})

    def test_long_text_is_bounded_and_json_serializable(self):
        samples = []
        parse(self.html.replace('+100', 'x' * 2000), self.f, self.url, self.now, samples)
        self.assertLessEqual(len(samples[0]['cell_text_repr']), 160)
        self.assertLessEqual(len(samples[0]['normalized_text_repr']), 160)
        json.dumps(samples, allow_nan=False)

    def test_collector_exports_samples_without_changing_valid_offers(self):
        text = self.html.replace('+100', 'bad')
        def loader(url):
            return '<a href="/sport/basketball/nba/matchup/388756/odds">game</a>' if url.endswith('/nba/odds') else text
        rows, errors = collect({'forecasts': [self.f]}, self.now, loader)
        self.assertEqual(len(rows), 5)
        self.assertEqual(errors[0]['rejected_cells'], 1)
        self.assertEqual(errors[0]['rejected_cell_samples'][0]['reason'], 'cell_format_mismatch')

    def test_optional_diagnostics_does_not_change_return_contract(self):
        text = self.html.replace('+100', 'bad')
        self.assertEqual(parse(text, self.f, self.url, self.now), parse(text, self.f, self.url, self.now, []))

    def test_collector_diagnostics_have_a_global_byte_budget(self):
        text = self.html
        for value in ('-1.5 -110', '+1.5 -110', 'o217.5 -107', 'u217.5 -113', '-119', '+100'):
            text = text.replace('>' + value + '<', '>invalid<')
        links = ''.join(f'<a href="/sport/basketball/nba/matchup/{n}/odds">game</a>'
                        for n in range(388756, 388786))
        def loader(url):
            return links if url.endswith('/nba/odds') else text
        rows, errors = collect({'forecasts': [self.f]}, self.now, loader)
        samples = [s for e in errors for s in e.get('rejected_cell_samples', [])]
        size = sum(len(json.dumps(s, ensure_ascii=True, separators=(',', ':')).encode()) + 1 for s in samples)
        self.assertEqual(rows, [])
        self.assertTrue(samples)
        self.assertLessEqual(size, 1536)
        self.assertTrue(any(e.get('diagnostic_samples_limited') for e in errors))
        self.assertEqual(sum(e.get('rejected_cells', 0) for e in errors), 180)
        header = {'generated_at_utc': self.now.isoformat(), 'protocol': 'test',
                  'execution_ok': True, 'betting_release': False, 'source_errors': errors,
                  'fixtures': [dict(self.f, context_path='reports/chat/0022600272.json', offer_count=0)] * 4,
                  'actual_offer_count': 0, 'computed_offer_count': 0}
        self.assertLess(len(json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode()), 10000)

    def test_wrong_date_is_still_rejected(self):
        with self.assertRaises(ValueError):
            parse(self.html, dict(self.f, start_time_utc='2026-11-21T01:00:00Z'), self.url, self.now, [])


if __name__ == '__main__':
    unittest.main()
