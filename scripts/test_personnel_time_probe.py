import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import duckdb
from personnel_time_probe import inspect,probe,write_report


class PersonnelTimeTests(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect();self.addCleanup(self.con.close)
        self.con.execute("ATTACH ':memory:' AS nba")
        self.con.execute('CREATE TABLE nba.injury_report(season INTEGER,report_time TIMESTAMPTZ,game_id VARCHAR,game_date DATE,team_id VARCHAR,player_id VARCHAR,status VARCHAR)')
        self.con.execute('CREATE TABLE nba.schedule(season INTEGER,game_id VARCHAR,start_time TIMESTAMPTZ,home_team_id VARCHAR,away_team_id VARCHAR)')
        self.con.execute('CREATE TABLE nba.rosters_daily(season INTEGER,as_of_date DATE,team_id VARCHAR,player_id VARCHAR)')
        self.con.execute("INSERT INTO nba.injury_report VALUES (2027,'2026-11-21 12:00:00+00','0022600001','2026-11-21','H','P','Questionable')")
        self.con.execute("INSERT INTO nba.schedule VALUES (2027,'0022600001','2026-11-21 18:00:00+00','H','A')")
        self.con.execute("INSERT INTO nba.rosters_daily VALUES (2027,'2026-11-20','H','P')")
        self.now=dt.datetime(2026,11,21,21,tzinfo=dt.timezone.utc)

    def result(self):return inspect(self.con,self.now)

    def test_before_tip_and_roster_do_not_grant_model_approval(self):
        r=self.result();self.assertEqual(r['before_scheduled_tip_rows'],1)
        self.assertEqual(r['matching_prior_date_roster_rows'],1)
        self.assertFalse(r['model_input_approved']);self.assertFalse(r['historical_publication_provenance_verified'])

    def test_equal_tip_is_not_pregame(self):
        self.con.execute("UPDATE nba.injury_report SET report_time='2026-11-21 18:00:00+00'")
        self.assertEqual(self.result()['at_or_after_scheduled_tip_rows'],1)

    def test_post_tip_is_not_pregame(self):
        self.con.execute("UPDATE nba.injury_report SET report_time='2026-11-21 19:00:00+00'")
        self.assertEqual(self.result()['before_scheduled_tip_rows'],0)

    def test_future_reports_are_counted_not_used(self):
        self.con.execute("UPDATE nba.injury_report SET report_time='2026-11-22 12:00:00+00'")
        r=self.result();self.assertEqual(r['sample_rows_read'],0);self.assertEqual(r['profile']['future_report_times'],1)

    def test_missing_schedule_not_imputed(self):
        self.con.execute('DELETE FROM nba.schedule')
        self.assertEqual(self.result()['sample'][0]['timing_relation'],'schedule_missing')

    def test_duplicate_schedule_not_collapsed_into_a_valid_game(self):
        self.con.execute('INSERT INTO nba.schedule SELECT * FROM nba.schedule')
        self.assertEqual(self.result()['sample'][0]['timing_relation'],'schedule_ambiguous')

    def test_wrong_team_is_flagged(self):
        self.con.execute("UPDATE nba.injury_report SET team_id='X'")
        self.assertIn('team_not_in_schedule',self.result()['sample'][0]['issues'])

    def test_eastern_date_and_same_day_roster_cutoff(self):
        self.con.execute("UPDATE nba.schedule SET start_time='2026-11-22 01:30:00+00'")
        self.con.execute("INSERT INTO nba.rosters_daily VALUES (2027,'2026-11-21','X','P')")
        r=self.result()['sample'][0]
        self.assertEqual(r['roster_relation'],'matching_prior_date_candidate')
        self.assertEqual(str(r['roster_candidates'][0]['as_of_date']),'2026-11-20')
        self.assertEqual(r['issues'],[])

    def test_missing_and_ambiguous_roster_stay_local(self):
        self.con.execute('DELETE FROM nba.rosters_daily')
        self.assertEqual(self.result()['sample'][0]['roster_relation'],'prior_date_missing')
        self.con.execute("INSERT INTO nba.rosters_daily VALUES (2027,'2026-11-20','H','P'),(2027,'2026-11-20','A','P')")
        self.assertEqual(self.result()['sample'][0]['roster_relation'],'prior_date_ambiguous')

    def test_duplicate_report_candidate_keys_flagged(self):
        self.con.execute('INSERT INTO nba.injury_report SELECT * FROM nba.injury_report')
        self.assertTrue(any('duplicate_candidate_key_in_sample' in x['issues'] for x in self.result()['sample']))

    def test_bound_and_schema_changes(self):
        with self.assertRaises(ValueError):inspect(self.con,self.now,11)
        self.con.execute('ALTER TABLE nba.schedule DROP COLUMN start_time')
        with self.assertRaises(ValueError):self.result()

    def test_failure_diagnostics_and_read_only_attach(self):
        con=Mock();con.execute.side_effect=OSError('offline')
        r=probe(self.now,Mock(return_value=con))
        self.assertFalse(r['execution_ok']);self.assertFalse(r['betting_release'])
        self.assertIn('READ_ONLY',con.execute.call_args.args[0]);con.close.assert_called_once()
        with tempfile.TemporaryDirectory() as folder:
            write_report(r,Path(folder))
            self.assertIn('offline',(Path(folder)/'personnel_time_probe.md').read_text())


if __name__=='__main__':
    unittest.main()
