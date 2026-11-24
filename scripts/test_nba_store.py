import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import duckdb
from nba_store import prepare, read_store, MAX_ROWS, rows

NOW=dt.datetime(2026,11,24,15,30,tzinfo=dt.timezone.utc)
class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.saved=self.root/'saved';self.n=0
        self.con=duckdb.connect();self.addCleanup(self.con.close)
        self.sql("ATTACH ':memory:' AS nba")
        self.sql("CREATE TABLE nba.players AS SELECT i::VARCHAR player_id,'Player '||i AS name,2026 first_season,2027 last_season FROM range(30) t(i)")
        self.sql("CREATE TABLE nba.team_seasons AS SELECT 2027 season,'T'||i team_id,true is_nba FROM range(30) t(i)")
        self.sql("CREATE TABLE nba.rosters_daily AS SELECT 2027 season,i::VARCHAR player_id,'T'||i team_id,DATE '2026-11-23' as_of_date FROM range(30) t(i)")
        self.sql("CREATE TABLE nba.schedule AS SELECT 2027 season,'0022600001' game_id")
        self.sql("CREATE TABLE nba.metadata(dataset VARCHAR,source VARCHAR,updated TIMESTAMPTZ)")
        for name in ('team_seasons','rosters_daily','schedule','team_game_logs','player_game_logs'):
            self.con.execute('INSERT INTO nba.metadata VALUES (?,?,?)',[name,'stats',NOW])
        self.sql("CREATE TABLE nba.team_game_logs AS SELECT y::INTEGER season,'002'||lpad((y-2001)::VARCHAR,2,'0')||'00001' game_id,'T0' team_id,'0' player_id,DATE '2025-01-01' game_date,10 pts FROM range(2023,2028) t(y)")
        self.sql("CREATE TABLE nba.player_game_logs AS SELECT *, 'T1' opp_team_id,0 AS min,0 fgm,0 fga,0 fg3m,0 fg3a,0 ftm,0 fta,0 oreb,0 dreb,0 reb,0 ast,0 tov,0 stl,0 blk,0 pf FROM nba.team_game_logs")
    def sql(self,s):return self.con.execute(s)
    def run_store(self):
        self.n+=1;stage=self.root/str(self.n)
        result=prepare(self.saved,stage,self.con,NOW,'run'+str(self.n),'code')
        return result,stage
    def bootstrap(self):
        r,s=self.run_store();s.rename(self.saved);return r
    def snapshot(self):return {str(p):p.read_bytes() for p in self.saved.rglob('*') if p.is_file()}
    def test_bootstrap(self):
        r=self.bootstrap();m,d=read_store(self.saved)
        self.assertEqual(r['roster_team_count'],30);self.assertEqual(len(d),11)
        self.assertFalse(m['model_input_approved']);self.assertFalse(m['betting_release'])
    def test_repeat(self):
        a=self.bootstrap();b,_=self.run_store();self.assertEqual(a['tables'],b['tables'])
    def test_new_player(self):
        self.bootstrap();self.sql("INSERT INTO nba.players VALUES ('NEW','New Player',2027,2027)")
        self.sql("INSERT INTO nba.rosters_daily VALUES (2027,'NEW','T0','2026-11-23')")
        r,_=self.run_store();self.assertEqual(r['changes']['new_source_player_ids'],['NEW'])
    def test_trade_preserves_old_day(self):
        self.bootstrap();self.sql("UPDATE nba.rosters_daily SET as_of_date='2026-11-24'")
        self.sql("UPDATE nba.rosters_daily SET team_id=CASE player_id WHEN '0' THEN 'T1' WHEN '1' THEN 'T0' ELSE team_id END")
        r,s=self.run_store();self.assertEqual(len(r['changes']['roster_changes']),2)
        self.assertEqual(len(read_store(s)[1]['rosters_daily/season=2027.jsonl']),60)
    def test_same_day_removal(self):
        self.sql("INSERT INTO nba.players VALUES ('EXTRA','Extra Player',2027,2027)")
        self.sql("INSERT INTO nba.rosters_daily VALUES (2027,'EXTRA','T0','2026-11-23')")
        self.bootstrap();self.sql("DELETE FROM nba.rosters_daily WHERE player_id='EXTRA'")
        _,s=self.run_store();self.assertEqual(len(read_store(s)[1]['rosters_daily/season=2027.jsonl']),30)
    def test_partial_league(self):
        self.bootstrap();before=self.snapshot();self.sql("DELETE FROM nba.rosters_daily WHERE player_id='0'")
        with self.assertRaises(ValueError):self.run_store()
        self.assertEqual(before,self.snapshot())
    def test_stale_metadata(self):
        self.bootstrap();before=self.snapshot();self.sql("UPDATE nba.metadata SET updated='2020-01-01'")
        with self.assertRaises(ValueError):self.run_store()
        self.assertEqual(before,self.snapshot())
    def test_duplicate_id(self):
        self.sql('INSERT INTO nba.players SELECT * FROM nba.players LIMIT 1')
        with self.assertRaises(ValueError):self.run_store()
    def test_duplicate_name_allowed(self):
        self.sql("UPDATE nba.players SET name='Same Name'");self.run_store()
    def test_unknown_roster_id(self):
        self.sql("UPDATE nba.rosters_daily SET player_id='UNKNOWN' WHERE player_id='0'")
        with self.assertRaises(ValueError):self.run_store()
    def test_catalog_disappearance_preserved(self):
        self.sql("INSERT INTO nba.players VALUES ('OLD','Old Player',2020,2025)");self.bootstrap()
        self.sql("DELETE FROM nba.players WHERE player_id='OLD'");_,s=self.run_store()
        self.assertFalse(next(r for r in read_store(s)[1]['players.jsonl'] if r['player_id']=='OLD')['source_present'])
    def test_stat_correction(self):
        self.bootstrap();before=self.snapshot();self.sql('UPDATE nba.player_game_logs SET pts=42 WHERE season=2027')
        _,s=self.run_store();self.assertEqual(read_store(s)[1]['player_game_logs/season=2027.jsonl'][0]['pts'],42)
        self.assertEqual(before,self.snapshot())
    def test_lost_game_key(self):
        self.bootstrap();self.sql('DELETE FROM nba.player_game_logs WHERE season=2027')
        with self.assertRaises(ValueError):self.run_store()
    def test_corrupt_saved_table(self):
        self.bootstrap();(self.saved/'players.jsonl').write_text('{}')
        with self.assertRaises(ValueError):self.run_store()
    def test_unsafe_manifest_path(self):
        self.bootstrap();p=self.saved/'manifest.json';m=json.loads(p.read_text());m['tables']['../bad.jsonl']={};p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):read_store(self.saved)
    def test_future_roster(self):
        self.sql("UPDATE nba.rosters_daily SET as_of_date='2027-01-01'")
        with self.assertRaises(ValueError):self.run_store()
    def test_no_inplace_write(self):
        with self.assertRaises(ValueError):prepare(self.saved,self.saved,self.con,NOW,'run','code')
    def test_roster_date_regression(self):
        self.bootstrap();self.sql("UPDATE nba.rosters_daily SET as_of_date='2026-11-22'")
        with self.assertRaises(ValueError):self.run_store()
    def test_overflow(self):
        class Huge:
            description=[('player_id',)]
            def execute(self,*a):return self
            def fetchmany(self,n):return [('P',)]*(MAX_ROWS+1)
        with self.assertRaises(ValueError):rows(Huge(),'query')
    def test_null_name_preserved_not_identity_usable(self):
        self.sql("UPDATE nba.players SET name=NULL WHERE player_id='0'")
        r,s=self.run_store();player=next(x for x in read_store(s)[1]['players.jsonl'] if x['player_id']=='0')
        self.assertIsNone(player['name']);self.assertFalse(player['identity_name_usable'])
        self.assertEqual(r['diagnostics']['catalog_quality']['unusable_name_rows'],1)
        self.assertEqual(r['diagnostics']['catalog_rows'],30)
        self.assertFalse(r['model_input_approved']);self.assertFalse(r['betting_release'])
    def test_blank_name_preserved(self):
        self.sql("UPDATE nba.players SET name='  ' WHERE player_id='0'")
        r,s=self.run_store();self.assertEqual(len(read_store(s)[1]['players.jsonl']),30)
        self.assertEqual(r['diagnostics']['catalog_quality']['usable_name_rows'],29)
    def test_all_names_missing_blocks(self):
        self.sql('UPDATE nba.players SET name=NULL')
        with self.assertRaisesRegex(ValueError,'no usable names: rows=30'):self.run_store()
    def test_empty_catalog_has_specific_error(self):
        self.sql('DELETE FROM nba.players')
        with self.assertRaisesRegex(ValueError,'empty: rows=0'):self.run_store()
    def test_oversized_catalog_has_specific_error(self):
        from nba_store import inspect_catalog
        with self.assertRaisesRegex(ValueError,'exceeds 20000 rows: rows=20001'):
            inspect_catalog([{'player_id':str(i),'name':'Name'} for i in range(20001)])
    def test_diagnostics_survive_later_failure(self):
        self.sql("UPDATE nba.players SET name=NULL WHERE player_id='0'")
        self.sql("DELETE FROM nba.rosters_daily WHERE player_id='1'")
        diagnostics={}
        with self.assertRaises(ValueError):prepare(self.saved,self.root/'failed',self.con,NOW,'run','code',diagnostics)
        self.assertEqual(diagnostics['stage'],'league_rosters')
        self.assertEqual(diagnostics['catalog_quality']['name_issues'],[{'player_id':'0','reason':'missing_or_invalid_name'}])
        self.assertFalse(self.saved.exists())
    def test_name_flag_is_true_for_usable_name(self):
        _,s=self.run_store()
        self.assertTrue(all(p['identity_name_usable'] for p in read_store(s)[1]['players.jsonl']))
if __name__=='__main__':unittest.main()
