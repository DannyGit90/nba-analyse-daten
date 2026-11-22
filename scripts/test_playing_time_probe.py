import datetime as dt
import unittest
from unittest.mock import Mock, patch
import playing_time_probe as target

NOW = dt.datetime(2026,11,22,tzinfo=dt.timezone.utc)
KEY = (2027,'0022600001','P1','T1',dt.date(2026,11,20))


class ProbeTests(unittest.TestCase):
    def connection(self, selected=None):
        con = Mock()
        cursor = con.execute.return_value
        cursor.description = [(k,) for k in ('season','game_id','player_id','team_id','sample_date')]
        cursor.fetchall.return_value = [KEY] if selected is None else selected
        return con

    def test_invalid_time_and_limit(self):
        for now,limit in [(NOW.replace(tzinfo=None),10),(NOW,0),(NOW,11),(NOW,True)]:
            with self.assertRaises(ValueError):
                target.inspect(self.connection(),now,limit)

    def test_empty_sample_not_success(self):
        with self.assertRaisesRegex(ValueError,'No eligible'):
            target.inspect(self.connection([]),NOW)

    def test_identical_keys_and_no_row_deduplication(self):
        con = self.connection()
        logs = [{'min':30.0},{'min':30.0}]
        boxes = [{'seconds_played':1800}]
        with patch.object(target,'fetch_exact',side_effect=[logs,boxes]) as fetch, patch.object(target,'compare_rows',return_value={'status_counts':{'ambiguous_key':1}}) as compare:
            report = target.inspect(con,NOW)
        self.assertEqual(fetch.call_args_list[0].args[2],fetch.call_args_list[1].args[2])
        compare.assert_called_once_with(logs,boxes)
        self.assertEqual(len(report['log_rows_repr']),2)
        self.assertEqual(con.execute.call_args.args[1],[2027,NOW.date(),10])

    def test_connection_failure_reported(self):
        result = target.probe(NOW,Mock(side_effect=RuntimeError('offline')))
        self.assertFalse(result['execution_ok'])
        self.assertFalse(result['comparison_executed'])
        self.assertFalse(result['source_read_attempted'])

    def test_success_is_not_unit_approval(self):
        con = self.connection()
        with patch.object(target,'inspect',return_value={'comparison':{'status_counts':{'observed_difference':1}}}):
            result = target.probe(NOW,lambda:con)
        self.assertTrue(result['execution_ok'])
        self.assertTrue(result['comparison_executed'])
        for field in ('units_verified','model_input_approved','production_model_changed','betting_release'):
            self.assertFalse(result[field])
        self.assertIn('(READ_ONLY)',con.execute.call_args_list[0].args[0])
        con.close.assert_called_once()

    def test_fetch_failure_keeps_comparison_incomplete(self):
        con = self.connection()
        with patch.object(target,'inspect',side_effect=ValueError('resource limit')):
            result = target.probe(NOW,lambda:con)
        self.assertFalse(result['execution_ok'])
        self.assertFalse(result['comparison_executed'])
        self.assertIn('resource limit',result['error'])
        con.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
