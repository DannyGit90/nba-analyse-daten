import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from source_capabilities import audit, inventory, write_report


class SourceCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026,11,21,20,tzinfo=dt.timezone.utc)
        self.con = Mock(); self.con.execute.return_value = self.con
        self.con.fetchall.return_value = [('main','sample','player_id','VARCHAR'),
            ('main','sample','team_id','VARCHAR'),('main','sample','game_id','VARCHAR'),
            ('main','sample','min','DOUBLE')]

    def test_read_only_inventory_and_explicit_limits(self):
        r = audit(self.now, Mock(return_value=self.con))
        self.assertTrue(r['execution_ok'])
        self.assertEqual(r['player_data_rows_imported'],0)
        self.assertFalse(r['historical_pregame_personnel_verified'])
        self.assertFalse(r['betting_release'])
        self.assertIn('READ_ONLY',self.con.execute.call_args_list[0].args[0])
        self.assertIn('possible_playing_time',r['tables'][0]['candidate_hints'])
        self.assertFalse(r['tables'][0]['semantics_verified'])
        self.con.close.assert_called_once()

    def test_absent_player_columns_do_not_create_player_data(self):
        self.con.fetchall.return_value = [('main','team_game_logs','team_id','VARCHAR')]
        r = audit(self.now,Mock(return_value=self.con))
        self.assertTrue(r['execution_ok'])
        self.assertEqual(r['candidate_table_count'],0)

    def test_empty_metadata_is_failure(self):
        self.con.fetchall.return_value=[]
        r=audit(self.now,Mock(return_value=self.con))
        self.assertFalse(r['execution_ok']);self.con.close.assert_called_once()

    def test_source_error_still_closes_connection(self):
        self.con.execute.side_effect=OSError('offline')
        r=audit(self.now,Mock(return_value=self.con))
        self.assertFalse(r['execution_ok']);self.assertIn('offline',r['error'])
        self.con.close.assert_called_once()

    def test_connection_failure_is_reported(self):
        r=audit(self.now,Mock(side_effect=OSError('connection failed')))
        self.assertFalse(r['execution_ok'])

    def test_report_saved_even_on_failure(self):
        r=audit(self.now,Mock(side_effect=OSError('offline')))
        with tempfile.TemporaryDirectory() as folder:
            write_report(r,Path(folder))
            self.assertFalse(json.loads((Path(folder)/'source_capabilities.json').read_text())['execution_ok'])
            self.assertIn('offline',(Path(folder)/'source_capabilities.md').read_text())


if __name__ == '__main__':
    unittest.main()
