import ast
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import duckdb
import pandas as pd
from local_model_source import fetch_local_snapshot,LOG_SQL,SCHEDULE_SQL,COLUMNS

NOW=dt.datetime(2026,11,24,20,tzinfo=dt.timezone.utc)
class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.data={f'team_game_logs/season={y}.jsonl':[dict(season=y,game_id='002'+str(y-2001).zfill(2)+'00001',team_id='T1',opp_team_id='T2',game_date='2026-11-22' if y==2027 else str(y)+'-01-02',home=None,pts=100,off_rating=110.0,def_rating=105.0,pace=98.0)] for y in range(2010,2028)}
        self.data['schedule/season=2027.jsonl']=[dict(season=2027,game_id=g,game_date='2026-11-25',start_time='2026-11-26T00:00:00+00:00',home_team_id='T1',away_team_id='T2',neutral_site=False,status='scheduled') for g in ('0012600001','0022600001')]
        self.data['team_seasons/season=2027.jsonl']=[dict(season=2027,team_id='T1',nba_abbrev='ONE',is_nba=True)]
        self.manifest={'schema':'nba-source-store-v1','execution_ok':True,'season':2027,'run_id':'fixture','observed_at_utc':NOW.isoformat(),'model_input_approved':False,'betting_release':False,
            'source_metadata':[dict(dataset=n,updated=NOW.isoformat()) for n in ('team_seasons','rosters_daily','schedule','team_game_logs','player_game_logs')],'tables':{}}
        self.save()
    def save(self):
        for name,rows in self.data.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            content=''.join(json.dumps(r)+'\n' for r in rows).encode();path.write_bytes(content)
            self.manifest['tables'][name]={'rows':len(rows),'sha256':hashlib.sha256(content).hexdigest()}
        body=json.dumps(self.manifest).encode();(self.root/'manifest.json').write_bytes(body);self.pin=hashlib.sha256(body).hexdigest()
    def load(self):return fetch_local_snapshot(2027,self.root,NOW,self.pin)
    def test_legacy_return_format_and_provenance(self):
        data,schedule,teams=self.load()
        self.assertIsInstance(data,pd.DataFrame);self.assertIsInstance(schedule,pd.DataFrame)
        self.assertEqual(teams,[('T1','ONE')]);self.assertEqual(len(data),18)
        proof=data.attrs['nba_store_evidence'];self.assertEqual(proof['manifest_sha256'],self.pin)
        self.assertFalse(proof['external_access_enabled']);self.assertFalse(proof['model_input_approved'])
    def test_identical_legacy_sql_constants(self):
        path=Path(__file__).with_name('paper_data_refresh.py')
        constants={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(path.read_text()).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('LOG_SQL','SCHEDULE_SQL')}
        self.assertEqual(LOG_SQL,constants['LOG_SQL']);self.assertEqual(SCHEDULE_SQL,constants['SCHEDULE_SQL'])
    def test_values_and_types_match_independent_json_sql_reference(self):
        expected=duckdb.connect();self.addCleanup(expected.close);expected.execute("ATTACH ':memory:' AS nba")
        for table,columns in COLUMNS.items():
            paths=[str(self.root/n) for n in self.data if n.startswith(table+'/')]
            specification='{'+','.join("'"+k+"':'"+v+"'" for k,v in columns.items())+'}'
            expected.execute('CREATE TABLE nba.main.'+table+" AS SELECT * FROM read_json(?,columns="+specification+",format='newline_delimited')",[paths])
        data,schedule,teams=self.load()
        pd.testing.assert_frame_equal(data,expected.execute(LOG_SQL,[2027]).df(),check_exact=True)
        pd.testing.assert_frame_equal(schedule,expected.execute(SCHEDULE_SQL,[2027]).df(),check_exact=True)
    def test_preseason_schedule_excluded_like_existing_loader(self):
        _,schedule,_=self.load();self.assertEqual(schedule.game_id.tolist(),['0022600001'])
    def test_null_home_not_imputed(self):
        data,_,_=self.load();self.assertTrue(data.home.isna().all())
    def test_no_saved_files_changed(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()};self.load()
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
    def test_wrong_manifest_pin(self):
        self.pin='0'*64
        with self.assertRaisesRegex(ValueError,'pin mismatch'):self.load()
    def test_corrupt_table(self):
        (self.root/'team_game_logs/season=2010.jsonl').write_text('{}\n')
        with self.assertRaisesRegex(ValueError,'hash'):self.load()
    def test_missing_history_rejected(self):
        del self.data['team_game_logs/season=2010.jsonl'];del self.manifest['tables']['team_game_logs/season=2010.jsonl'];self.save()
        with self.assertRaisesRegex(ValueError,'season=2010'):self.load()
    def test_empty_history_rejected(self):
        self.data['team_game_logs/season=2010.jsonl']=[];self.save()
        with self.assertRaisesRegex(ValueError,'Empty required historical'):self.load()
    def test_stale_and_future_snapshots_rejected(self):
        for value in ('2026-11-23T00:00:00+00:00','2026-11-25T00:00:00+00:00'):
            with self.subTest(value=value):
                self.manifest['observed_at_utc']=value;self.save()
                with self.assertRaisesRegex(ValueError,'Stale or future'):self.load()
    def test_missing_columns_rejected(self):
        del self.data['team_game_logs/season=2010.jsonl'][0]['pace'];self.save()
        with self.assertRaisesRegex(ValueError,'Missing columns'):self.load()
    def test_numeric_id_not_coerced(self):
        self.data['team_game_logs/season=2010.jsonl'][0]['team_id']=123;self.save()
        with self.assertRaisesRegex(ValueError,'String required'):self.load()
    def test_fractional_points_not_coerced(self):
        self.data['team_game_logs/season=2010.jsonl'][0]['pts']=100.5;self.save()
        with self.assertRaisesRegex(ValueError,'Integer required'):self.load()
    def test_duplicate_game_team_rejected(self):
        self.data['team_game_logs/season=2010.jsonl']*=2;self.save()
        with self.assertRaisesRegex(ValueError,'duplicate key'):self.load()
    def test_bad_source_metadata_rejected(self):
        self.manifest['source_metadata']=[];self.save()
        with self.assertRaisesRegex(ValueError,'Incomplete source metadata'):self.load()
    def test_season_mismatch_rejected(self):
        self.manifest['season']=2026;self.save()
        with self.assertRaisesRegex(ValueError,'matching store'):self.load()
if __name__=='__main__':unittest.main()
