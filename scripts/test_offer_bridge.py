import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from offer_bridge import build,group_offers,load_offers,side_context,validate

GEN = '2026-11-23T10:00:00+00:00'
NOW = dt.datetime(2026,11,23,11,tzinfo=dt.timezone.utc)
TIP = dt.datetime(2026,11,24,1,tzinfo=dt.timezone.utc)
HEADER = {'generated_at_utc':GEN,'protocol':'test'}


def offer(**changes):
    o = {'game_id':'0022600295','bookmaker':'A','source':'s','observed_at_utc':'2026-11-23T10:30:00+00:00','price_timestamp_utc':None,
         'price_status':'indirect_reference_time_unknown','rules_verified':False,'betting_release':False,'market':'spread','side':'home',
         'odds':1.9,'line':-13.5,'recommendation':None,'p_experimental':0.52,'calculation_status':'computed_reference_only'}
    o.update(changes);return o


def game():
    review = {'players':[{'player_id':'P','source_name':'Out Player','availability_evidence':'reported_out','recorded_fga_share':0.2,'candidate_for_further_role_review':False},
        {'player_id':'Q','source_name':'Maybe','availability_evidence':'conditional','recorded_fga_share':0.1,'candidate_for_further_role_review':False},
        {'player_id':'R','source_name':'No Profile','availability_evidence':'reported_out','recorded_fga_share':None,'candidate_for_further_role_review':False},
        {'player_id':'S','source_name':'Option','availability_evidence':'explicit_available','recorded_fga_share':0.05,'candidate_for_further_role_review':True}]}
    people = {'status':'reported_statuses_only','records':[{'reported_status':'Out','source_name':'Out Player','database_match_verified':True},
        {'reported_status':'Questionable','source_name':'Maybe','database_match_verified':True},{'reported_status':'Out','source_name':'Unmatched','database_match_verified':False}]}
    return {'game_id':'0022600295','home':'LAL','away':'UTA','status':'descriptive_team_analysis_only','start_time_utc':TIP.isoformat(),
        'teams':{'home':{'rest_days':2},'away':{'rest_days':0}},'personnel':{'home':people,'away':{'status':'not_submitted','records':[]}},
        'replacement_review':{'home':review,'away':{}}}


def write_root(root,offers):
    (root/'chat').mkdir()
    (root/'paper_latest.json').write_text(json.dumps(HEADER))
    (root/'chat'/'0022600295.json').write_text(json.dumps(dict(HEADER,fixture={'game_id':'0022600295'},market_pages=['reports/chat/0022600295-markets-0.json'])))
    (root/'chat'/'0022600295-markets-0.json').write_text(json.dumps(dict(HEADER,offers=offers)))


def report():
    return {'execution_ok':True,'source_generated_at_utc':GEN,'protocol':'test','replacement_review':{'status':'evidence_screen_only'},'fixtures':[game()]}


class OfferBridgeTests(unittest.TestCase):
    def test_grouping_best_price_and_gaps(self):
        s = group_offers([offer(),offer(bookmaker='B',odds=1.95),offer(side='away',line=13.5)],TIP,NOW)
        home = next(x for x in s if x['side']=='home')
        self.assertEqual(home['provider_count'],2)
        self.assertEqual(home['best_odds'],1.95)
        self.assertEqual(home['best_bookmakers'],['B'])
        for needed in ('independent_line_probability_missing','offer_rules_unverified','price_time_unknown'):
            self.assertIn(needed,home['gaps'])
        self.assertEqual(home['assessment']['status'],'UNGEPRUEFT')
        self.assertIsNone(home['assessment']['color'])
        self.assertFalse(home['paper_reference']['usable_for_filter'])

    def test_integer_line_duplicate_and_single_provider_flags(self):
        s = group_offers([offer(line=-14.0),offer(line=-14.0,odds=1.8)],TIP,NOW)[0]
        for flag in ('integer_line_push_rules','duplicate_provider_rows','single_provider_reference'):
            self.assertIn(flag,s['gaps'])
        self.assertEqual(len(s['prices']),2)

    def test_time_and_calculation_flags(self):
        s = group_offers([offer(observed_at_utc='2026-11-24T01:00:00+00:00',calculation_status='integer_blocked')],TIP,NOW)[0]
        self.assertIn('observed_at_or_after_start',s['gaps'])
        self.assertIn('paper_calculation_missing',s['gaps'])
        self.assertAlmostEqual(group_offers([offer()],TIP,NOW)[0]['oldest_observation_age_minutes'],30.)

    def test_inconsistent_paper_probabilities_not_collapsed(self):
        s = group_offers([offer(),offer(bookmaker='B',p_experimental=0.6)],TIP,NOW)[0]
        self.assertIn('inconsistent_paper_probability',s['gaps'])
        self.assertIsNone(s['paper_reference']['p_experimental'])

    def test_invalid_offers_rejected(self):
        for changes in [dict(market='props'),dict(side='over'),dict(odds=1.0),dict(odds=float('nan')),dict(odds=True),
                        dict(line=None),dict(market='moneyline'),dict(betting_release=True),dict(recommendation='GREEN'),dict(bookmaker=' ')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate(offer(**changes))

    def test_team_context_exact_shares_and_open_gaps(self):
        home = side_context(game(),'home')
        self.assertAlmostEqual(home['reported_out_recorded_fga_share'],0.2)
        self.assertEqual(home['reported_out_without_profile'],1)
        self.assertAlmostEqual(home['conditional_recorded_fga_share'],0.1)
        self.assertEqual(home['unresolved_identity_names'],['Unmatched'])
        self.assertEqual(home['candidate_names'],['Option'])
        away = side_context(game(),'away')
        self.assertEqual(away['personnel_status'],'not_submitted')
        self.assertEqual(away['reported_status_counts'],{})

    def test_build_from_snapshot_without_changing_input(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);write_root(root,[offer(),offer(side='away',line=13.5)])
            r = report();before = copy.deepcopy(r)
            out = build(r,root,NOW)
        self.assertEqual(out['offer_bridge']['status'],'offers_bound_unassessed')
        self.assertEqual(out['offer_bridge']['selection_count'],2)
        self.assertFalse(out['offer_bridge']['analysis_complete'])
        self.assertEqual(r,before)

    def test_snapshot_game_and_path_mismatches_isolated_per_game(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);write_root(root,[offer(game_id='0022600296')])
            out = build(report(),root,NOW)
        self.assertEqual(out['offer_bridge']['status'],'partial_failure')
        self.assertEqual(out['fixtures'][0]['offer_bridge']['status'],'unavailable')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);write_root(root,[offer()])
            context = json.loads((root/'chat'/'0022600295.json').read_text())
            context['market_pages'] = ['reports/chat/../../secret.json']
            (root/'chat'/'0022600295.json').write_text(json.dumps(context))
            with self.assertRaises(ValueError):load_offers(root,'0022600295',HEADER)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);write_root(root,[offer()])
            r = report();r['source_generated_at_utc'] = '2026-11-22T10:00:00+00:00'
            with self.assertRaisesRegex(ValueError,'mismatch'):build(r,root,NOW)

    def test_started_game_and_missing_evidence_are_not_bound(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);write_root(root,[offer()])
            r = report();r['fixtures'][0]['start_time_utc'] = NOW.isoformat()
            self.assertEqual(build(r,root,NOW)['fixtures'][0]['offer_bridge']['status'],'started_not_assessed')
            r = report();r['replacement_review']['status'] = 'blocked'
            out = build(r,root,NOW)
            self.assertEqual(out['offer_bridge']['status'],'blocked')
            self.assertNotIn('offer_bridge',out['fixtures'][0])


if __name__ == '__main__':
    unittest.main()
