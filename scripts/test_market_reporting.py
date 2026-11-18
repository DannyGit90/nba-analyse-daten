import copy
import json
import tempfile
import unittest
from pathlib import Path
from finalize_market_reports import BOOKS, bookmaker, prepare, priority, coverage, finalize


def offer(book='FanDuel FanDuel', market='moneyline', side='home', line=None, p=.7, q=1.6):
    row = {'game_id': '0022600258', 'bookmaker': book, 'market': market, 'side': side,
           'line': line, 'odds': q, 'p_experimental': p, 'paper_ev': p * q - 1,
           'break_even': 1 / q, 'paper_fair_odds': 1 / p,
           'calculation_status': 'computed_reference_only', 'recommendation': None,
           'betting_release': False, 'rules_verified': False,
           'price_status': 'indirect_reference_time_unknown', 'source': 'https://example.org/odds',
           'observed_at_utc': '2026-11-18T18:00:00Z', 'price_timestamp_utc': None}
    return row


class ReportingTests(unittest.TestCase):
    def test_known_names_only(self):
        for x in BOOKS:
            self.assertEqual(bookmaker(x + ' ' + x), x)
        self.assertEqual(bookmaker('Caesars Odds Caesars Odds'), 'Caesars')
        self.assertEqual(bookmaker('Unknown Unknown'), 'Unknown Unknown')

    def test_duplicate_provenance_and_immutability(self):
        a, b = offer(), offer(book='FanDuel')
        b['source'] = 'https://example.net/odds'
        original = copy.deepcopy([a, b])
        rows = prepare([a, b])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]['provenance']), 2)
        self.assertEqual([a, b], original)
        self.assertEqual(prepare(rows), rows)

    def test_different_prices_lines_rules_preserved(self):
        a = offer(market='spread', line=-2.5)
        cases = [a, dict(a, odds=1.7, paper_ev=.7 * 1.7 - 1, break_even=1 / 1.7), dict(a, line=-3.5), dict(a, includes_overtime=True)]
        self.assertEqual(len(prepare(cases)), 4)

    def test_conflicting_calculations_rejected(self):
        a = offer()
        with self.assertRaises(ValueError):
            prepare([a, dict(a, p_experimental=.8)])

    def test_probability_then_ev_with_price_buckets(self):
        high_p = offer(book='BetMGM', p=.8, q=1.3)
        high_ev = offer(book='FanDuel', p=.6, q=2.)
        poor_price = offer(book='bet365', p=.95, q=1.01)
        missing = dict(offer(book='DraftKings'), calculation_status='not_computed', reason='unsupported')
        rows = prepare([missing, high_ev, poor_price, high_p])
        self.assertEqual([r['bookmaker'] for r in rows], ['BetMGM', 'FanDuel', 'bet365', 'DraftKings'])
        self.assertTrue(all(r['recommendation'] is None and r['betting_release'] is False for r in rows))
        self.assertGreater(priority(offer(p=.7, q=1.8)), priority(offer(p=.7, q=1.6)))

    def test_wrong_arithmetic_rejected(self):
        with self.assertRaises(ValueError):
            prepare([dict(offer(), paper_ev=.99)])

    def test_inventory_not_claimed_complete(self):
        rows = prepare([offer(market='spread', line=-2.5), offer(market='spread', line=-3.5)])
        c = coverage(rows)
        self.assertEqual(c['spread']['provider_lines']['FanDuel']['home'], [-3.5, -2.5])
        self.assertTrue(c['spread']['same_provider_side_multiple_lines_observed'])
        self.assertFalse(c['spread']['full_alternative_ladder_verified'])
        self.assertEqual(c['total']['offers'], 0)

    def make_run(self, root):
        header = {'generated_at_utc': '2026-11-18T18:00:00Z', 'protocol': 'test'}
        paper = dict(header, execution_ok=True, money_betting_released=False, forecasts=[], research_extension={})
        index = dict(header, execution_ok=True, fixtures=[], actual_offer_count=648, computed_offer_count=620)
        remaining = 28
        for i in range(12):
            gid = f'002260{258 + i:04d}'
            rows = []
            for book in BOOKS:
                for market, sides in [('moneyline', ['home', 'away']), ('spread', ['home', 'away']), ('total', ['over', 'under'])]:
                    for side in sides:
                        line = None if market == 'moneyline' else -2.5 if market == 'spread' else 220.5
                        r = dict(offer(book=book + ' ' + book, market=market, side=side, line=line), game_id=gid)
                        if market == 'total' and remaining:
                            r.update(line=220, calculation_status='not_computed', reason='Only half-point lines supported; no integer or quarter lines')
                            for k in ['p_experimental', 'paper_ev', 'paper_fair_odds', 'break_even']:
                                r.pop(k)
                            remaining -= 1
                        rows.append(r)
            context = dict(header, fixture={'game_id': gid}, market_pages=[])
            for n in range(0, len(rows), 5):
                path = f'chat/{gid}-markets-{n // 5}.json'
                self.write(root, path, dict(header, offers=rows[n:n + 5]))
                context['market_pages'].append('reports/' + path)
            self.write(root, f'chat/{gid}.json', context)
            index['fixtures'].append({'game_id': gid, 'context_path': f'reports/chat/{gid}.json'})
            paper['forecasts'].append({'game_id': gid, 'p_home_experimental': .7})
        self.write(root, 'paper_latest.json', paper)
        self.write(root, 'chat_index.json', index)
        (root / 'paper_log').mkdir()
        (root / 'paper_log/keep.json').write_text('preserved')
        return paper

    def write(self, root, path, obj):
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj))

    def test_full_twelve_game_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = self.make_run(root)
            result = finalize(root)
            self.assertEqual((result['input_offer_count'], result['unique_offer_count']), (648, 648))
            self.assertEqual(sum(result['uncomputed_reasons'].values()), 28)
            self.assertEqual(len(result['fixtures']), 12)
            p = json.loads((root / 'paper_latest.json').read_text())
            self.assertEqual(p['forecasts'], original['forecasts'])
            self.assertFalse(p['money_betting_released'])
            self.assertEqual((root / 'paper_log/keep.json').read_text(), 'preserved')
            active = ['paper_latest.json', 'chat_index.json', 'market_coverage.json']
            for f in result['fixtures']:
                context = json.loads((root / f"chat/{f['game_id']}.json").read_text())
                active += [f"chat/{f['game_id']}.json", f"chat/{f['game_id']}-coverage.json"]
                active += [x.removeprefix('reports/') for x in context['market_pages']]
            for path in active:
                self.assertLessEqual((root / path).stat().st_size, 16000 if path == 'paper_latest.json' else 10000)
            self.assertEqual(finalize(root)['unique_offer_count'], 648)

    def test_snapshot_mismatch_does_not_rewrite_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_run(root)
            p = root / 'chat/0022600258-markets-0.json'
            obj = json.loads(p.read_text()); obj['protocol'] = 'wrong'; p.write_text(json.dumps(obj))
            before = (root / 'paper_latest.json').read_bytes()
            with self.assertRaises(ValueError):
                finalize(root)
            self.assertEqual((root / 'paper_latest.json').read_bytes(), before)
            self.assertFalse((root / 'market_coverage.json').exists())

    def test_unsafe_page_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_run(root)
            p = root / 'chat/0022600258.json'
            obj = json.loads(p.read_text()); obj['market_pages'] = ['../../secret']; p.write_text(json.dumps(obj))
            with self.assertRaises(ValueError):
                finalize(root)

    def test_release_and_invalid_markets_rejected(self):
        for change in [{'betting_release': True}, {'recommendation': 'GREEN'}, {'odds': float('nan')}, {'market': 'player_points'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare([dict(offer(), **change)])


if __name__ == '__main__':
    unittest.main()
