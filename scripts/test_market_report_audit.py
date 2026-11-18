import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from audit_market_reports import audit, BRANDS


class AuditTests(unittest.TestCase):
    def write(self, path, obj):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, separators=(',', ':')))

    def load(self, path):
        return json.loads((self.root / path).read_text())

    def build(self):
        h = {'generated_at_utc': '2026-11-18T18:35:23+00:00', 'protocol': 'synthetic-test'}
        paper = dict(h, execution_ok=True, money_betting_released=False, forecasts=[], research_extension={'actual_offer_count':648, 'computed_offer_count':622})
        index = dict(h, execution_ok=True, betting_release=False, fixtures=[], actual_offer_count=648, computed_offer_count=622)
        manifest = dict(h, execution_ok=True, betting_release=False, fixtures=[], full_alternative_coverage_verified=False,
                        input_offer_count=648, unique_offer_count=648, duplicates_removed=0, uncomputed_reasons={'Unsupported integer':26})
        remaining = 26
        for n in range(12):
            gid = f'002260{258+n:04d}'
            rows = []
            for book in BRANDS:
                for market in ['moneyline','spread','total']:
                    for side in (['over','under'] if market == 'total' else ['home','away']):
                        r = {'game_id':gid, 'market':market, 'side':side, 'line':None if market=='moneyline' else 220.5 if market=='total' else 2.5,
                             'odds':2., 'bookmaker':book, 'bookmaker_raw':book+' '+book,
                             'source':'https://example.org/odds', 'observed_at_utc':h['generated_at_utc'], 'price_timestamp_utc':None,
                             'betting_release':False, 'recommendation':None, 'rules_verified':False}
                        r['provenance'] = [{k:r[k] for k in ('source','observed_at_utc','price_timestamp_utc','bookmaker_raw')}]
                        if market=='total' and remaining:
                            r.update(line=220, calculation_status='not_computed', reason='Unsupported integer', priority_bucket='not_rankable')
                            remaining-=1
                        else:
                            p=.6 if side in ('home','over') else .4
                            r.update(calculation_status='computed_reference_only', p_experimental=p, paper_ev=p*2-1,
                                     break_even=.5, paper_fair_odds=1/p,
                                     priority_bucket='positive_paper_ev_unvalidated' if p>.5 else 'nonpositive_paper_ev')
                        rows.append(r)
            rows.sort(key=lambda r:(0,-1,-1e100) if r['calculation_status']=='not_computed' else (2 if r['paper_ev']>0 else 1,r['p_experimental'],r['paper_ev']),reverse=True)
            pages=[]
            for start in range(0,54,8):
                path=f'chat/{gid}-markets-{start//8}.json'
                self.write(path,dict(h,offers=rows[start:start+8],betting_release=False))
                pages.append('reports/'+path)
            cp=f'reports/chat/{gid}-coverage.json'
            self.write(f'chat/{gid}.json',dict(h,fixture={'game_id':gid},market_pages=pages,coverage_path=cp))
            groups={}
            for market in ['moneyline','spread','total']:
                part=[r for r in rows if r['market']==market]
                sides=sorted({r['side'] for r in part})
                providers={}
                for r in part:
                    if r['line'] is not None:
                        providers.setdefault(r['bookmaker'],{}).setdefault(r['side'],[]).append(r['line'])
                groups[market]={'offers':18,'providers':9,'selections':len({(r['side'],r['line']) for r in part}),
                                'computed':sum(r['calculation_status']=='computed_reference_only' for r in part),
                                'uncomputed_reasons':{'Unsupported integer':sum(r['calculation_status']=='not_computed' for r in part)} if any(r['calculation_status']=='not_computed' for r in part) else {},
                                'lines_by_side':{s:sorted({r['line'] for r in part if r['side']==s and r['line'] is not None}) for s in sides},
                                'provider_lines':providers,'same_provider_side_multiple_lines_observed':False,
                                'full_alternative_ladder_verified':False,'scope':'observed_references_only'}
            self.write(cp.removeprefix('reports/'),dict(h,game_id=gid,markets=groups,betting_release=False,full_alternative_ladder_verified=False))
            index['fixtures'].append({'game_id':gid,'offer_count':54,'context_path':f'reports/chat/{gid}.json','coverage_path':cp})
            manifest['fixtures'].append({'game_id':gid,'offers':54,'coverage_path':cp,'market_counts':{'moneyline':18,'spread':18,'total':18}})
            paper['forecasts'].append({'game_id':gid})
        self.write('paper_latest.json',paper); self.write('chat_index.json',index);self.write('market_coverage.json',manifest)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'reports';self.build()

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_twelve_games(self):
        r=audit(self.root)
        self.assertEqual((r['fixtures_checked'],r['offers_checked'],r['computed_checked'],r['not_computed_checked']),(12,648,622,26))

    def test_corruptions_rejected(self):
        path='chat/0022600258-markets-0.json'
        original=self.load(path)
        changes=[lambda x:x.update(protocol='wrong'),lambda x:x['offers'][0].update(paper_ev=123),
                 lambda x:x['offers'][0].update(provenance=[]),lambda x:x['offers'][0].update(bookmaker='Bad'),
                 lambda x:x['offers'][0].update(betting_release=True),lambda x:x['offers'].append(copy.deepcopy(x['offers'][0]))]
        for mutation in changes:
            with self.subTest(mutation=mutation):
                obj=copy.deepcopy(original);mutation(obj);self.write(path,obj)
                with self.assertRaises(ValueError):audit(self.root)
                self.write(path,original)

    def test_cross_page_order_rejected(self):
        path='chat/0022600258.json';obj=self.load(path)
        obj['market_pages'].reverse();self.write(path,obj)
        with self.assertRaises(ValueError):audit(self.root)

    def test_inventory_mismatch_rejected(self):
        path='chat/0022600258-coverage.json';obj=self.load(path)
        obj['markets']['spread']['provider_lines']['FanDuel']['home']=[99.5];self.write(path,obj)
        with self.assertRaises(ValueError):audit(self.root)

    def test_count_mismatch_rejected(self):
        obj=self.load('chat_index.json');obj['computed_offer_count']=620;self.write('chat_index.json',obj)
        with self.assertRaises(ValueError):audit(self.root)

    def test_unsafe_page_rejected(self):
        path='chat/0022600258.json';obj=self.load(path)
        obj['market_pages']=['../../secret'];self.write(path,obj)
        with self.assertRaises(ValueError):audit(self.root)

    def test_read_only_and_unreferenced_pages(self):
        self.write('chat/0022600258-markets-99.json',{'old':'ignored'})
        archive=self.root.parent/'paper_log';archive.mkdir();(archive/'old.json').write_text('unchanged')
        before={str(p.relative_to(self.root.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.parent.rglob('*') if p.is_file()}
        self.assertEqual(audit(self.root)['unreferenced_market_pages_ignored'],1)
        after={str(p.relative_to(self.root.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.parent.rglob('*') if p.is_file()}
        self.assertEqual(before,after)


if __name__=='__main__':
    unittest.main()
