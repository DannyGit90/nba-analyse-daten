import copy
import datetime as dt
import json
import unittest
from unittest.mock import patch
from analysis_personnel import bind,digest

NOW = dt.datetime(2026,11,22,21,tzinfo=dt.timezone.utc)


def fixture():
    section = {'game_date_et':'2026-11-22','home':'H','away':'A','team':'H','status':'reported_raw',
        'parsing_complete':True,'errors':[],'players':[{'name_candidate':'Name, Player','status':'Questionable','reason_text':'Injury'}]}
    raw = b'{}'
    p = {'execution_ok':True,'betting_release':False,'generated_at_utc':'2026-11-22T20:02:00+00:00',
        'source_checked_at_utc':'2026-11-22T20:01:00+00:00','source_published_at_utc':'2026-11-22T20:00:00+00:00',
        'source':'official-fixture','source_snapshot_sha256':digest(raw),'sections':[section]}
    pb = json.dumps(p).encode()
    r = {'section_index':0,'source_record_index':0,'game_date_et':'2026-11-22','home':'H','away':'A','team':'H',
         'name_candidate':'Name, Player','status':'Questionable','expected_team_id':'HT',
         'match':{'match_verified':True,'player_id':'P1'}}
    i = {'execution_ok':True,'betting_release':False,'generated_at_utc':'2026-11-22T20:03:00+00:00',
         'source_published_at_utc':p['source_published_at_utc'],'raw_snapshot_sha256':digest(raw),
         'player_snapshot_sha256':digest(pb),'records':[r]}
    report = {'execution_ok':True,'fixtures':[{'game_id':'0022600285','home':'H','away':'A','start_time_utc':'2026-11-23T01:00:00+00:00',
        'status':'descriptive_team_analysis_only','teams':{'home':{'team':'H','team_id':'HT'},'away':{'team':'A','team_id':'AT'}},'findings':[]}],
        'analysis_complete':False,'betting_release':False}
    return report,raw,p,i


def run_case(report,raw,p,i,now=NOW):
    pb = json.dumps(p).encode()
    i = copy.deepcopy(i);i['player_snapshot_sha256'] = digest(pb)
    with patch('analysis_personnel.replay',return_value={k:v for k,v in p.items() if k!='source_snapshot_sha256'}):
        return bind(report,raw,pb,json.dumps(i).encode(),now)


class PersonnelBindingTests(unittest.TestCase):
    def test_bound_status_without_impact_or_recommendation(self):
        report,raw,p,i = fixture();before = copy.deepcopy(report)
        out = run_case(report,raw,p,i)
        player = out['fixtures'][0]['personnel']['home']['records'][0]
        self.assertEqual(player['player_id'],'P1')
        self.assertEqual(player['availability_scenarios'],['plays','does_not_play'])
        self.assertIsNone(player['scenario_weights'])
        self.assertFalse(player['impact_quantified'])
        self.assertFalse(out['analysis_complete'])
        self.assertEqual(report,before)

    def test_wrong_team_identity_not_assigned(self):
        report,raw,p,i = fixture();i['records'][0]['expected_team_id'] = 'OTHER'
        self.assertIsNone(run_case(report,raw,p,i)['fixtures'][0]['personnel']['home']['records'][0]['player_id'])

    def test_missing_and_not_submitted_distinct(self):
        report,raw,p,i = fixture();p['sections'][0]['status'] = 'not_submitted'
        out = run_case(report,raw,p,i)['fixtures'][0]['personnel']
        self.assertEqual(out['home']['status'],'not_submitted')
        self.assertEqual(out['away']['status'],'missing_section')
        self.assertFalse(out['away']['absence_of_entry_means_healthy'])

    def test_hash_replay_and_duplicate_guards(self):
        report,raw,p,i = fixture()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):run_case(report,b'{"changed":true}',p,i)
        with patch('analysis_personnel.replay',return_value={'sections':[]}):
            with self.assertRaisesRegex(ValueError,'replay mismatch'):
                bind(report,raw,json.dumps(p).encode(),json.dumps(i).encode(),NOW)
        i['records'].append(i['records'][0])
        with self.assertRaisesRegex(ValueError,'Duplicate identity'):run_case(report,raw,p,i)

    def test_stale_or_future_source(self):
        report,raw,p,i = fixture()
        for now in [NOW+dt.timedelta(hours=8),NOW-dt.timedelta(hours=2)]:
            with self.assertRaises(ValueError):run_case(report,raw,p,i,now)

    def test_started_not_enriched(self):
        report,raw,p,i = fixture();report['fixtures'][0]['start_time_utc'] = NOW.isoformat()
        self.assertEqual(run_case(report,raw,p,i)['fixtures'][0]['personnel']['status'],'started_not_assessed')

    def test_ambiguous_section_not_used(self):
        report,raw,p,i = fixture();p['sections'].append(copy.deepcopy(p['sections'][0]))
        self.assertEqual(run_case(report,raw,p,i)['fixtures'][0]['personnel']['home']['status'],'ambiguous_sections')


if __name__ == '__main__':
    unittest.main()
