import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from nba_history import extend_history,validate_closed_season,write_stage,compact_status

NOW=dt.datetime(2026,11,24,17,tzinfo=dt.timezone.utc)
def season_rows(year):
    rows=[]
    for i in range(0,30,2):
        gid='002'+str(year-2001).zfill(2)+str(i).zfill(5)
        for t,o,p in ((i,i+1,100),(i+1,i,90)):
            rows.append(dict(season=year,game_id=gid,team_id='T'+str(t),opp_team_id='T'+str(o),game_date=str(year)+'-01-01',pts=p,home=None))
    return rows

class HistoryTests(unittest.TestCase):
    def test_backfill_preserves_existing_tables(self):
        old={'team_game_logs/season=2026.jsonl':season_rows(2026),'players.jsonl':[{'player_id':'X'}]}
        calls=[]
        def fetch(y):calls.append(y);return season_rows(y)
        data,proof=extend_history(old,fetch,NOW)
        self.assertNotIn(2026,calls);self.assertEqual(len(proof['closed_season_checks']),17)
        self.assertIs(data['players.jsonl'],old['players.jsonl']);self.assertEqual(len(old),2)
        self.assertEqual(calls,list(range(2010,2026)))
    def test_repeat_needs_no_historical_download(self):
        data,_=extend_history({},season_rows,NOW)
        def forbidden(y):raise AssertionError('unexpected re-download')
        _,proof=extend_history(data,forbidden,NOW);self.assertEqual(proof['fetched_seasons'],[])
    def test_automatic_season_rollover(self):
        _,proof=extend_history({},season_rows,dt.datetime(2027,10,2,tzinfo=dt.timezone.utc))
        self.assertEqual(proof['current_season'],2028);self.assertEqual(proof['closed_season_checks'][-1]['season'],2027)
    def test_empty_season_rejected(self):
        with self.assertRaisesRegex(ValueError,'Empty'):validate_closed_season([],2026,NOW.date())
    def test_partial_team_coverage_rejected(self):
        with self.assertRaises(ValueError):validate_closed_season(season_rows(2026)[:-2],2026,NOW.date())
    def test_duplicate_key_rejected(self):
        values=season_rows(2026);values.append(dict(values[0]))
        with self.assertRaises(ValueError):validate_closed_season(values,2026,NOW.date())
    def test_unpaired_game_rejected(self):
        values=season_rows(2026);values[0]['game_id']='0022509999'
        with self.assertRaisesRegex(ValueError,'Incomplete'):validate_closed_season(values,2026,NOW.date())
    def test_wrong_opponent_rejected(self):
        values=season_rows(2026);values[0]['opp_team_id']='T7'
        with self.assertRaisesRegex(ValueError,'Conflicting'):validate_closed_season(values,2026,NOW.date())
    def test_tied_result_rejected(self):
        values=season_rows(2026);values[1]['pts']=100
        with self.assertRaisesRegex(ValueError,'Conflicting'):validate_closed_season(values,2026,NOW.date())
    def test_null_home_flags_are_not_imputed(self):
        values=season_rows(2026);validate_closed_season(values,2026,NOW.date())
        self.assertTrue(all(r['home'] is None for r in values))
    def test_future_date_rejected(self):
        values=season_rows(2026);values[0]['game_date']='2030-01-01'
        with self.assertRaises(ValueError):validate_closed_season(values,2026,NOW.date())
    def test_fetch_failure_does_not_mutate_input(self):
        old={'players.jsonl':[]}
        def failed(y):raise OSError('offline')
        with self.assertRaises(OSError):extend_history(old,failed,NOW)
        self.assertEqual(old,{'players.jsonl':[]})
    def test_safe_staging_and_hashes(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'stage';values=season_rows(2026)
            result=write_stage({'team_game_logs/season=2026.jsonl':values},{'schema':'nba-source-store-v1'},path,{})
            body=(path/'team_game_logs/season=2026.jsonl').read_bytes()
            self.assertEqual(result['tables']['team_game_logs/season=2026.jsonl']['sha256'],hashlib.sha256(body).hexdigest())
            with self.assertRaises(ValueError):write_stage({},result,path,{})
    def test_unsafe_path_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):write_stage({'../bad.jsonl':[]},{},Path(folder)/'stage',{})
    def test_compact_status_excludes_large_identity_lists(self):
        report={'execution_ok':True,'tables':{},'changes':{'new_source_player_ids':['X']*5000},'diagnostics':{'catalog_quality':{'rows':5000,'unusable_name_rows':1}}}
        result=compact_status(report,'previous-sha',{'history_stage_ok':True})
        self.assertEqual(result['new_source_player_count'],5000);self.assertLess(len(json.dumps(result)),2000)
        self.assertEqual(result['previous_manifest_sha256'],'previous-sha');self.assertFalse(result['betting_release'])
    def test_failed_collection_is_not_reported_successful(self):
        result=compact_status({'execution_ok':False,'error':'capture failed'},'previous-sha',{'history_stage_ok':True})
        self.assertFalse(result['execution_ok']);self.assertTrue(result['history_stage_ok'])
        self.assertEqual(result['error'],'capture failed')
if __name__=='__main__':unittest.main()
