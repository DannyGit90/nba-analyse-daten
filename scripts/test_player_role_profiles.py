import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path
import duckdb
from player_role_profiles import load,summarize,enrich

CUTOFF = dt.date(2026,11,22)


class ContributionProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        path = str(Path(self.tmp.name)/'fixture.duckdb')
        c = duckdb.connect(path)
        c.execute('CREATE TABLE team_game_logs(season INTEGER,game_id VARCHAR,team_id VARCHAR,game_date DATE)')
        c.execute('CREATE TABLE schedule(season INTEGER,game_id VARCHAR,game_date DATE,home_team_id VARCHAR,away_team_id VARCHAR,status VARCHAR)')
        c.execute('CREATE TABLE player_game_logs(season INTEGER,game_id VARCHAR,player_id VARCHAR,team_id VARCHAR,game_date DATE,pts INTEGER,fga INTEGER,fg3a INTEGER,ast INTEGER,reb INTEGER)')
        for gid,date,status in [('0022600001','2026-11-20','final'),('0022600002','2026-11-22','final'),('0022600003','2026-11-21','scheduled')]:
            c.execute('INSERT INTO team_game_logs VALUES(2027,?,?,?)',[gid,'T',date])
            c.execute('INSERT INTO schedule VALUES(2027,?,?,?,?,?)',[gid,date,'T','A',status])
            c.execute('INSERT INTO player_game_logs VALUES(2027,?,?,?,?,20,15,5,6,7)',[gid,'P','T',date])
        c.close()
        self.db = duckdb.connect();self.addCleanup(self.db.close)
        self.db.execute("ATTACH '"+path.replace("'","''")+"' AS nba (READ_ONLY)")

    def test_real_sql_excludes_current_date_and_unfinished_games(self):
        r = load(self.db,2027,'T',CUTOFF)
        self.assertEqual(r['team_game_count'],1)
        self.assertEqual(r['games'][0]['game_id'],'0022600001')
        self.assertEqual(r['profiles'][0]['mean_per_record']['fga'],15.)
        self.assertEqual(r['profiles'][0]['replacement_suitability'],'not_assessed')

    def record(self,**changes):
        r = {'game_id':'G','player_id':'P','team_id':'T','game_date':dt.date(2026,11,20),'pts':20,'fga':15,'fg3a':5,'ast':6,'reb':7}
        r.update(changes);return r

    def test_duplicate_identity_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            summarize([self.record(),self.record()],['G'],'T',CUTOFF)

    def test_invalid_stats_rejected(self):
        for changes in [dict(ast=None),dict(pts=True),dict(fga=-1),dict(fg3a=16),dict(reb=7.0)]:
            with self.assertRaises(ValueError):summarize([self.record(**changes)],['G'],'T',CUTOFF)

    def test_missing_data_not_zero_filled(self):
        with self.assertRaises(ValueError):summarize([],['G'],'T',CUTOFF)
        with self.assertRaises(ValueError):summarize([self.record()],['G','MISSING'],'T',CUTOFF)

    def test_wrong_team_or_future_date_rejected(self):
        for changes in [dict(team_id='OTHER'),dict(game_date=CUTOFF),dict(player_id=None)]:
            with self.assertRaises(ValueError):summarize([self.record(**changes)],['G'],'T',CUTOFF)

    def test_blocked_personnel_does_not_open_source(self):
        def forbidden():raise AssertionError('Unexpected source access')
        r = enrich({'fixtures':[]},dt.datetime(2026,11,22,tzinfo=dt.timezone.utc),forbidden)
        self.assertEqual(r['role_profiles']['status'],'blocked')
        self.assertFalse(r['role_profiles']['source_read_attempted'])

    def test_readonly_fixture(self):
        with self.assertRaises(duckdb.Error):self.db.execute('DELETE FROM nba.main.player_game_logs')


    def test_enrichment_uses_database_identity_and_retains_open_roles(self):
        db = self.db
        class Adapter:
            def execute(self,sql,params=None):
                if sql.startswith('ATTACH '):
                    if '(READ_ONLY)' not in sql:raise AssertionError('Write attachment')
                    return self
                return db.execute(sql,[] if params is None else params)
            def close(self):pass
        g = {'game_id':'0022600285','status':'descriptive_team_analysis_only','start_time_utc':'2026-11-23T01:00:00+00:00',
             'teams':{'home':{'team_id':'T'},'away':{'team_id':'A'}},
             'personnel':{'home':{'records':[{'player_id':'P','database_match_verified':True},{'player_id':None,'database_match_verified':False}]}}}
        report = {'personnel_evidence':{'status':'bound_snapshot_only','published_at_utc':'2026-11-22T20:00:00+00:00'},'fixtures':[g],
                  'analysis_complete':False,'betting_release':False}
        before = copy.deepcopy(report)
        r = enrich(report,dt.datetime(2026,11,22,21,tzinfo=dt.timezone.utc),lambda:Adapter())
        self.assertEqual(r['role_profiles']['status'],'partial_failure')
        self.assertEqual(r['role_profiles']['team_profiles'],1)
        people = r['fixtures'][0]['personnel']['home']['records']
        self.assertEqual(people[0]['contribution_status'],'matched_recent_records')
        self.assertEqual(people[1]['contribution_status'],'identity_unresolved')
        self.assertIsNone(people[1]['historical_contributions'])
        self.assertFalse(r['analysis_complete'])
        self.assertFalse(r['betting_release'])
        self.assertEqual(report,before)


if __name__ == '__main__':
    unittest.main()
