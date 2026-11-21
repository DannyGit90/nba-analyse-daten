import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import duckdb
from player_source_probe import inspect,probe,write_report


class PlayerProbeTests(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect();self.addCleanup(self.con.close)
        self.con.execute("ATTACH ':memory:' AS nba")
        self.con.execute('CREATE TABLE nba.player_game_logs(season INTEGER,game_id VARCHAR,player_id VARCHAR,team_id VARCHAR,opp_team_id VARCHAR,game_date DATE,min DOUBLE)')
        self.con.execute('CREATE TABLE nba.players(player_id VARCHAR,name VARCHAR,first_season INTEGER,last_season INTEGER)')
        self.con.execute("INSERT INTO nba.player_game_logs VALUES (2027,'0022600001','P1','H','A','2026-11-20',32.5)")
        self.con.execute("INSERT INTO nba.players VALUES ('P1','Synthetic Player',2020,2027)")
        self.now=dt.datetime(2026,11,21,21,tzinfo=dt.timezone.utc)

    def test_actual_queries_profile_and_identity(self):
        r=inspect(self.con,self.now)
        self.assertTrue(r['sample_basic_checks_ok'])
        self.assertEqual(r['sample_rows_read'],1)
        self.assertEqual(r['identities'][0]['example_name'],'Synthetic Player')
        self.assertFalse(r['historical_pregame_personnel_verified'])
        self.assertFalse(r['minutes_semantics_verified'])

    def test_current_day_and_future_excluded_from_sample(self):
        self.con.execute("INSERT INTO nba.player_game_logs VALUES (2027,'0022600002','P1','H','A','2026-11-21',30),(2027,'0022600003','P1','H','A','2026-11-22',30)")
        r=inspect(self.con,self.now)
        self.assertEqual(r['sample_rows_read'],1)
        self.assertEqual(r['profile']['season_rows'],3)

    def test_duplicate_keys_detected_in_sample(self):
        self.con.execute('INSERT INTO nba.player_game_logs SELECT * FROM nba.player_game_logs')
        self.assertFalse(inspect(self.con,self.now)['sample_basic_checks_ok'])

    def test_missing_and_ambiguous_identities(self):
        self.con.execute('DELETE FROM nba.players')
        self.assertIn('player_id_not_found',inspect(self.con,self.now)['sample_issues'][0]['reasons'])
        self.con.execute("INSERT INTO nba.players VALUES ('P1','First',2020,2027),('P1','Second',2020,2027)")
        r=inspect(self.con,self.now)
        self.assertIn('ambiguous_player_id',r['sample_issues'][0]['reasons'])
        self.assertIsNone(r['identities'][0]['example_name'])

    def test_invalid_minutes_and_zero_not_absence(self):
        self.con.execute('UPDATE nba.player_game_logs SET min=-1')
        self.assertIn('invalid_minutes_field',inspect(self.con,self.now)['sample_issues'][0]['reasons'])
        self.con.execute('UPDATE nba.player_game_logs SET min=0')
        self.assertTrue(inspect(self.con,self.now)['sample_basic_checks_ok'])

    def test_nan_is_flagged_and_json_safe(self):
        self.con.execute("UPDATE nba.player_game_logs SET min='NaN'::DOUBLE")
        r=inspect(self.con,self.now)
        self.assertFalse(r['sample_basic_checks_ok'])
        json.dumps(r,default=str,allow_nan=False)

    def test_empty_sample_not_approved(self):
        self.con.execute('DELETE FROM nba.player_game_logs')
        self.assertFalse(inspect(self.con,self.now)['sample_basic_checks_ok'])

    def test_sample_bound_and_missing_columns(self):
        with self.assertRaises(ValueError):inspect(self.con,self.now,100)
        self.con.execute('ALTER TABLE nba.players DROP COLUMN name')
        with self.assertRaises(ValueError):inspect(self.con,self.now)

    def test_read_only_attach_and_close_on_error(self):
        con=Mock();con.execute.side_effect=OSError('offline')
        r=probe(self.now,Mock(return_value=con))
        self.assertFalse(r['execution_ok']);self.assertFalse(r['betting_release'])
        self.assertIn('READ_ONLY',con.execute.call_args.args[0]);con.close.assert_called_once()

    def test_error_report_is_published(self):
        r=probe(self.now,Mock(side_effect=OSError('offline')))
        with tempfile.TemporaryDirectory() as folder:
            write_report(r,Path(folder))
            self.assertIn('offline',(Path(folder)/'player_source_probe.md').read_text())


if __name__=='__main__':
    unittest.main()
