import tempfile
import unittest
from pathlib import Path
import duckdb
from playing_time_fetch import fetch_exact


class FetchExactIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'source.duckdb')
        writer = duckdb.connect(self.path)
        try:
            writer.execute('CREATE TABLE player_game_logs(season INTEGER,game_id VARCHAR,player_id VARCHAR,team_id VARCHAR,game_date DATE,min DOUBLE)')
            writer.execute('CREATE TABLE player_box(season INTEGER,game_id VARCHAR,player_id VARCHAR,team_id VARCHAR,seconds_played INTEGER)')
            writer.execute("INSERT INTO player_game_logs VALUES(2027,'0022600001','P1','T1','2026-11-20',30.0)")
            writer.execute("INSERT INTO player_box VALUES(2027,'0022600001','P1','T1',1800)")
        finally:
            writer.close()
        self.db = duckdb.connect()
        self.addCleanup(self.db.close)
        self.attach()
        self.key = [{'season': 2027, 'game_id': '0022600001', 'player_id': 'P1', 'team_id': 'T1'}]

    def attach(self):
        self.db.execute("ATTACH '" + self.path.replace("'", "''") + "' AS nba (READ_ONLY)")

    def mutate_fixture(self, sql):
        self.db.execute('DETACH nba')
        writer = duckdb.connect(self.path)
        try:
            writer.execute(sql)
        finally:
            writer.close()
        self.attach()

    def test_both_columns(self):
        logs = fetch_exact(self.db, 'player_game_logs', self.key)
        boxes = fetch_exact(self.db, 'player_box', self.key)
        self.assertEqual((logs[0]['min'], boxes[0]['seconds_played']), (30.0, 1800))
        for field, value in self.key[0].items():
            self.assertEqual(logs[0][field], value)
            self.assertEqual(boxes[0][field], value)

    def test_duplicates_preserved(self):
        self.mutate_fixture('INSERT INTO player_box SELECT * FROM player_box')
        self.assertEqual(len(fetch_exact(self.db, 'player_box', self.key)), 2)

    def test_missing_column_fails(self):
        self.mutate_fixture('ALTER TABLE player_box RENAME COLUMN seconds_played TO seconds')
        with self.assertRaisesRegex(ValueError, 'column missing'):
            fetch_exact(self.db, 'player_box', self.key)

    def test_invalid_inputs_and_empty_keys(self):
        self.assertEqual(fetch_exact(self.db, 'player_box', []), [])
        for table, keys in [('schedule', self.key), ('player_box', [dict(self.key[0], season=True)]),
                            ('player_box', self.key * 2), ('player_box', self.key * 201)]:
            with self.subTest(table=table, count=len(keys)):
                with self.assertRaises(ValueError):
                    fetch_exact(self.db, table, keys)

    def test_overflow_not_truncated(self):
        self.mutate_fixture('INSERT INTO player_box SELECT * FROM player_box')
        with self.assertRaisesRegex(ValueError, 'resource limit'):
            fetch_exact(self.db, 'player_box', self.key, max_rows=1)

    def test_readonly_source(self):
        with self.assertRaises(duckdb.Error):
            self.db.execute('DELETE FROM nba.main.player_box')

    def test_missing_side_not_filled(self):
        self.mutate_fixture('DELETE FROM player_box')
        self.assertEqual(fetch_exact(self.db, 'player_box', self.key), [])
        self.assertEqual(len(fetch_exact(self.db, 'player_game_logs', self.key)), 1)

    def test_wrong_seconds_type_rejected(self):
        self.mutate_fixture('ALTER TABLE player_box ALTER COLUMN seconds_played TYPE DOUBLE')
        with self.assertRaisesRegex(ValueError, 'not INTEGER'):
            fetch_exact(self.db, 'player_box', self.key)


if __name__ == '__main__':
    unittest.main()
