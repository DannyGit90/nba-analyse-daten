import datetime as dt
import unittest
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

    def test_source_failure_exposed(self):
        def loader(url):
            raise OSError('unavailable')
        rows, errors = collect({'forecasts': [self.f]}, self.now, loader)
        self.assertEqual(rows, [])
        self.assertTrue(any('No valid' in str(e) for e in errors))


if __name__ == '__main__':
    unittest.main()
