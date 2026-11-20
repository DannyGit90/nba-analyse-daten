"""Synthetic readiness and non-invasive capture tests; not a live repair acceptance."""
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from pipeline_readiness import build_readiness, collect_espn, main, numeric_fields


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 20, 16, tzinfo=dt.timezone.utc)
        self.f = {'game_id':'0022600043','home':'ATL','away':'CHA','start_time_utc':'2026-11-21T00:00:00Z'}
        self.p = {'generated_at_utc':self.now.isoformat(),'protocol':'test','execution_ok':True,
                  'money_betting_released':False,'forecasts':[self.f]}
        self.rows = [{'game_id':self.f['game_id'],'market':'moneyline','side':s,
                      'calculation_status':'computed_reference_only','betting_release':False,
                      'recommendation':None} for s in ('home','away')]
        self.i = dict({k:self.p[k] for k in ('generated_at_utc','protocol')}, execution_ok=True,
                      betting_release=False,actual_offer_count=2,computed_offer_count=2,
                      fixtures=[{'game_id':self.f['game_id'],'context_path':'reports/chat/0022600043.json'}])

    def report(self):
        return build_readiness(self.p,self.i,self.rows)

    def test_import_calculation_assessment_separated(self):
        r=self.report()['fixtures'][0]['markets']
        self.assertEqual(r['moneyline']['capture'],'both_sides_observed')
        self.assertEqual(r['moneyline']['computed'],2)
        self.assertEqual(r['moneyline']['assessment'],'not_recorded_by_pipeline')
        self.assertEqual(r['total']['capture'],'missing')

    def test_single_side_is_partial(self):
        self.rows.pop();self.i.update(actual_offer_count=1,computed_offer_count=1)
        self.assertEqual(self.report()['fixtures'][0]['markets']['moneyline']['capture'],'partial_sides')

    def test_uncomputed_total_does_not_block_moneyline(self):
        self.rows.append(dict(self.rows[0],market='total',side='under',calculation_status='not_computed'))
        self.i['actual_offer_count']=3
        r=self.report()['fixtures'][0]['markets']
        self.assertEqual(r['total']['uncomputed'],1)
        self.assertEqual(r['moneyline']['computed'],2)

    def test_no_decisions_or_releases_invented(self):
        r=self.report()
        self.assertIsNone(r['recommendation_count'])
        self.assertFalse(r['betting_release'])
        self.assertFalse(r['model_evidence']['automatic_release'])
        self.assertIn('No chat decisions imported or overwritten',r['assessment_note'])

    def test_large_sample_and_validation_flag_do_not_release(self):
        e={'protocol':'test','execution_ok':True,'games_scored':100000,
           'favorite_selection_profile':{'calibration_validated':True}}
        r=build_readiness(self.p,self.i,self.rows,e)
        self.assertFalse(r['betting_release'])
        self.assertFalse(r['model_evidence']['sample_size_alone_can_authorize_release'])

    def test_evaluation_mismatch_explicit(self):
        r=build_readiness(self.p,self.i,self.rows,{'protocol':'other','execution_ok':True,'games_scored':100})
        self.assertEqual(r['model_evidence']['evaluation_status'],'missing_or_mismatched')
        self.assertIsNone(r['model_evidence']['games_scored'])

    def test_stale_snapshot_rejected(self):
        self.i['generated_at_utc']='old'
        with self.assertRaises(ValueError):self.report()

    def test_wrong_counts_rejected(self):
        self.i['actual_offer_count']=3
        with self.assertRaises(ValueError):self.report()

    def test_released_offer_rejected(self):
        self.rows[0]['betting_release']=True
        with self.assertRaises(ValueError):self.report()

    def test_inputs_unchanged(self):
        before=copy.deepcopy((self.p,self.i,self.rows));self.report()
        self.assertEqual((self.p,self.i,self.rows),before)

    def test_numeric_capture_omits_links_and_teams(self):
        fields=numeric_fields({'moneyline':{'home':{'close':{'odds':'-230'},'open':{'odds':'-200'}}},
                              'provider':{'id':'100'},'link':{'href':'https://example.org'},'team':{'id':'1'}})
        self.assertEqual(fields,{'moneyline.home.close.odds':'-230','moneyline.home.open.odds':'-200'})

    def test_capture_reuses_response_without_extra_request(self):
        payload={'events':[{'date':self.f['start_time_utc'],'status':{'type':{'state':'pre'}},
            'competitions':[{'date':self.f['start_time_utc'],'competitors':[
                {'homeAway':'home','team':{'abbreviation':'ATL'}},
                {'homeAway':'away','team':{'abbreviation':'CHA'}}],
                'odds':[{'provider':{'name':'Test'},'moneyline':{'home':{'close':{'odds':'-230'}}}}]}]}]}
        loader=Mock(return_value=payload);before=copy.deepcopy(payload)
        def core(paper,now,loader):
            self.assertIs(loader('https://example.org'),payload)
            return self.rows,[]
        with tempfile.TemporaryDirectory() as tmp:
            rows,errors=collect_espn(self.p,self.now,loader,Path(tmp),collector=core)
            r=json.loads((Path(tmp)/'espn_price_fields.json').read_text())
            self.assertEqual(r['samples'][0]['numeric_fields']['moneyline.home.close.odds'],'-230')
        self.assertIs(rows,self.rows);self.assertEqual(errors,[])
        loader.assert_called_once();self.assertEqual(payload,before)

    def test_diagnostic_failure_preserves_offers(self):
        with patch('pipeline_readiness.save',side_effect=OSError('unwritable')):
            rows,errors=collect_espn(self.p,self.now,collector=lambda *a,**k:(self.rows,[]))
        self.assertIs(rows,self.rows)
        self.assertIn('not saved',errors[-1]['error'])

    def test_publication_and_index_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'chat').mkdir()
            h={k:self.p[k] for k in ('generated_at_utc','protocol')}
            data={'paper_latest.json':self.p,'chat_index.json':self.i,
                  'chat/0022600043.json':dict(h,fixture=self.f,market_pages=['reports/chat/0022600043-markets-0.json']),
                  'chat/0022600043-markets-0.json':dict(h,offers=self.rows)}
            for path,obj in data.items():(root/path).write_text(json.dumps(obj))
            main(root)
            self.assertEqual(json.loads((root/'chat_index.json').read_text())['pipeline_readiness_path'],
                             'reports/pipeline_readiness.json')
            self.assertTrue(json.loads((root/'pipeline_readiness.json').read_text())['execution_ok'])
            self.assertEqual(json.loads((root/'paper_latest.json').read_text()),self.p)
            self.assertEqual(json.loads((root/'chat/0022600043-markets-0.json').read_text())['offers'],self.rows)


if __name__=='__main__':unittest.main()
