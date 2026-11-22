import copy
import datetime as dt
import unittest
from team_analysis import analyze

GEN = '2026-11-22T17:00:00+00:00'
NOW = dt.datetime(2026,11,22,18,tzinfo=dt.timezone.utc)


def fixture():
    forecast = {'game_id':'0022600285','home':'NYK','away':'IND','home_team_id':'H','away_team_id':'A','start_time_utc':'2026-11-23T01:00:00+00:00'}
    f = dict(forecast)
    for side,tid,off,defense in [('home','H',115.,109.),('away','A',110.,114.)]:
        f[side+'_context'] = {'team_id':tid,'season_games':16,'last10_games':10,'latest_game_date':'2026-11-21','rest_days_uncapped':0,
            'season_mean_per_game':{'off_rating':off,'def_rating':defense,'pace':99.},
            'last10_mean_per_game':{'off_rating':off+1,'def_rating':defense-1,'pace':98.}}
    return {'generated_at_utc':GEN,'protocol':'test','fixture':f},forecast


class TeamAnalysisTests(unittest.TestCase):
    def test_contrasts_and_form(self):
        p,f = fixture()
        r = analyze(p,f,GEN,'test',NOW)
        self.assertEqual(r['home_minus_away']['season']['net_rating'],10.)
        self.assertEqual(r['teams']['home']['last10_minus_season']['net_rating'],2.)
        self.assertIsNone(r['recommendation'])
        self.assertFalse(r['betting_release'])
        self.assertIn('current_personnel_and_replacement_roles',r['missing'])

    def test_input_unchanged(self):
        p,f = fixture();before = copy.deepcopy(p)
        analyze(p,f,GEN,'test',NOW)
        self.assertEqual(p,before)

    def test_snapshot_and_identity_guards(self):
        for field,value in [('protocol','other'),('generated_at_utc','2026-11-21T17:00:00+00:00')]:
            p,f = fixture();p[field] = value
            with self.assertRaises(ValueError):analyze(p,f,GEN,'test',NOW)
        p,f = fixture();p['fixture']['home'] = 'OTHER'
        with self.assertRaises(ValueError):analyze(p,f,GEN,'test',NOW)

    def test_started_and_outside_window(self):
        p,f = fixture()
        f['start_time_utc'] = NOW.isoformat();p['fixture']['start_time_utc'] = NOW.isoformat()
        self.assertEqual(analyze(p,f,GEN,'test',NOW)['status'],'started_not_assessed')
        p,f = fixture();f['start_time_utc'] = '2026-11-25T01:00:00+00:00';p['fixture']['start_time_utc'] = f['start_time_utc']
        self.assertEqual(analyze(p,f,GEN,'test',NOW)['status'],'outside_window_not_assessed')

    def test_invalid_numbers_counts_and_rest(self):
        for value in [None,True,float('nan'),float('inf'),-1,0]:
            p,f = fixture();p['fixture']['home_context']['last10_mean_per_game']['pace'] = value
            with self.assertRaises(ValueError):analyze(p,f,GEN,'test',NOW)
        for key,value in [('last10_games',11),('season_games',True),('rest_days_uncapped',1)]:
            p,f = fixture();p['fixture']['home_context'][key] = value
            with self.assertRaises(ValueError):analyze(p,f,GEN,'test',NOW)

    def test_nonhistorical_data(self):
        p,f = fixture();p['fixture']['home_context']['latest_game_date'] = '2026-11-22'
        with self.assertRaises(ValueError):analyze(p,f,GEN,'test',NOW)

    def test_stale_or_future_source(self):
        p,f = fixture()
        for now in [NOW-dt.timedelta(hours=2),NOW+dt.timedelta(hours=8)]:
            with self.assertRaises(ValueError):analyze(p,f,GEN,'test',now)


    def test_build_snapshot_paths_and_partial_failure(self):
        import json,tempfile
        from pathlib import Path
        from team_analysis import build
        page,f = fixture()
        paper = {'generated_at_utc':GEN,'protocol':'test','execution_ok':True,'money_betting_released':False,'forecasts':[f]}
        index = {'generated_at_utc':GEN,'protocol':'test','execution_ok':True,'betting_release':False,
                 'fixtures':[{'game_id':f['game_id'],'context_path':'reports/chat/'+f['game_id']+'.json'}]}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);(root/'chat').mkdir()
            (root/'paper_latest.json').write_text(json.dumps(paper))
            (root/'chat_index.json').write_text(json.dumps(index))
            (root/'chat'/ (f['game_id']+'.json')).write_text(json.dumps(page))
            report = build(root,NOW)
            self.assertTrue(report['execution_ok'])
            self.assertFalse(report['analysis_complete'])
            self.assertEqual(len(report['fixtures'][0]['context_sha256']),64)
            index['fixtures'][0]['context_path'] = '../../secret'
            (root/'chat_index.json').write_text(json.dumps(index))
            report = build(root,NOW)
            self.assertFalse(report['execution_ok'])
            self.assertEqual(report['fixtures'][0]['status'],'context_error')
            index['fixtures'].append(index['fixtures'][0])
            (root/'chat_index.json').write_text(json.dumps(index))
            with self.assertRaises(ValueError):build(root,NOW)


if __name__ == '__main__':
    unittest.main()
