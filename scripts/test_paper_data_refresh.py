"""Synthetic refresh and two-team completeness tests; no live-source acceptance."""
import copy
import datetime as dt
import unittest
from unittest.mock import Mock, patch
from paper_data_refresh import load_checked, fetch_snapshot, LOG_SQL, SCHEDULE_SQL


class Frame(list):
    def to_dict(self, orient):
        assert orient == 'records'
        return copy.deepcopy(list(self))


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 21, 10, tzinfo=dt.timezone.utc)
        self.schedule = Frame([{'game_id':'0022600050','game_date':'2026-11-20',
            'home_team_id':'H','away_team_id':'A','status':'final'}])
        self.rows = Frame([{'season':2027,'game_id':'0022600050','game_date':'2026-11-20',
            'team_id':t,'opp_team_id':o,'home':h,'pts':p,
            'off_rating':110.0,'def_rating':105.0,'pace':99.0}
            for t,o,h,p in [('H','A',True,110),('A','H',False,105)]])

    def snapshot(self, rows=None, schedule=None):
        return (self.rows if rows is None else rows,
                self.schedule if schedule is None else schedule,[('H','H'),('A','A')])

    def test_complete_source_only_read_once(self):
        snapshot=self.snapshot();loader=Mock(return_value=snapshot)
        out,r=load_checked(2027,self.now,loader)
        self.assertIs(out,snapshot);loader.assert_called_once_with(2027)
        self.assertEqual(r['status'],'not_needed')

    def test_missing_rows_recovered_once(self):
        first=self.snapshot(Frame());second=self.snapshot()
        loader=Mock(side_effect=[first,second]);out,r=load_checked(2027,self.now,loader)
        self.assertIs(out,second);self.assertEqual(loader.call_count,2)
        self.assertEqual((r['status'],r['unresolved_game_ids']),('recovered',[]))

    def test_single_team_row_not_complete(self):
        first=self.snapshot(Frame(self.rows[:1]));loader=Mock(side_effect=[first,self.snapshot()])
        _,r=load_checked(2027,self.now,loader)
        self.assertEqual(r['initial_incomplete_game_ids'],['0022600050'])
        self.assertEqual(r['status'],'recovered')

    def test_persistent_gap_keeps_first_snapshot(self):
        first=self.snapshot(Frame());loader=Mock(return_value=first)
        out,r=load_checked(2027,self.now,loader)
        self.assertIs(out,first);self.assertEqual(loader.call_count,2)
        self.assertEqual(r['unresolved_game_ids'],['0022600050'])

    def test_retry_exception_preserves_first(self):
        first=self.snapshot(Frame());loader=Mock(side_effect=[first,OSError('offline')])
        out,r=load_checked(2027,self.now,loader)
        self.assertIs(out,first);self.assertEqual(r['status'],'refresh_failed')
        self.assertTrue(r['unresolved_game_ids'])

    def test_retry_cannot_remove_final(self):
        first=self.snapshot(Frame());second=self.snapshot(Frame(),Frame())
        _,r=load_checked(2027,self.now,Mock(side_effect=[first,second]))
        self.assertEqual(r['status'],'refresh_failed')

    def test_retry_cannot_change_teams(self):
        first=self.snapshot(Frame());s=copy.deepcopy(self.schedule);s[0]['away_team_id']='X'
        _,r=load_checked(2027,self.now,Mock(side_effect=[first,self.snapshot(schedule=s)]))
        self.assertEqual(r['status'],'refresh_failed')

    def test_retry_cannot_lose_previous_history(self):
        history=dict(self.rows[0],game_id='0022600001',game_date='2026-11-01')
        first=self.snapshot(Frame([history]));second=self.snapshot()
        _,r=load_checked(2027,self.now,Mock(side_effect=[first,second]))
        self.assertEqual(r['status'],'refresh_failed')

    def test_both_rows_must_match_schedule(self):
        variants=[('opp_team_id','X'),('home',None),('team_id','X'),
                  ('game_date','2026-11-19'),('pts',True),('pts',float('nan')),
                  ('off_rating',0),('pace',float('inf'))]
        for key,value in variants:
            rows=copy.deepcopy(self.rows);rows[0][key]=value
            with self.subTest(key=key,value=value):
                _,r=load_checked(2027,self.now,Mock(return_value=self.snapshot(rows)))
                self.assertTrue(r['unresolved_game_ids'])

    def test_duplicate_rows_rejected(self):
        rows=Frame(self.rows+[copy.deepcopy(self.rows[0])])
        _,r=load_checked(2027,self.now,Mock(return_value=self.snapshot(rows)))
        self.assertTrue(r['unresolved_game_ids'])

    def test_final_tie_rejected(self):
        rows=copy.deepcopy(self.rows);rows[1]['pts']=110
        _,r=load_checked(2027,self.now,Mock(return_value=self.snapshot(rows)))
        self.assertTrue(r['unresolved_game_ids'])

    def test_same_utc_day_stays_excluded(self):
        s=copy.deepcopy(self.schedule);s[0]['game_date']='2026-11-21'
        loader=Mock(return_value=self.snapshot(Frame(),s))
        _,r=load_checked(2027,self.now,loader)
        loader.assert_called_once();self.assertEqual(r['unresolved_game_ids'],[])

    def test_nonfinal_does_not_trigger_refresh(self):
        s=copy.deepcopy(self.schedule);s[0]['status']='pre'
        loader=Mock(return_value=self.snapshot(Frame(),s))
        _,r=load_checked(2027,self.now,loader)
        loader.assert_called_once();self.assertEqual(r['unresolved_game_ids'],[])

    def test_duplicate_completed_schedule_rejected(self):
        s=Frame(self.schedule+self.schedule)
        with self.assertRaises(ValueError):
            load_checked(2027,self.now,Mock(return_value=self.snapshot(schedule=s)))

    def test_newly_seen_final_checked_on_retry(self):
        first=self.snapshot(Frame());s=copy.deepcopy(self.schedule)
        s.append(dict(s[0],game_id='0022600051'))
        _,r=load_checked(2027,self.now,Mock(side_effect=[first,self.snapshot(schedule=s)]))
        self.assertEqual(r['status'],'still_incomplete')
        self.assertTrue(r['unresolved_game_ids'])

    def test_initial_source_failure_not_hidden(self):
        with self.assertRaises(OSError):
            load_checked(2027,self.now,Mock(side_effect=OSError('offline')))

    def test_inputs_not_modified_and_never_release(self):
        initial=self.snapshot(Frame(self.rows[:1]));candidate=self.snapshot()
        before=copy.deepcopy((initial,candidate))
        _,r=load_checked(2027,self.now,Mock(side_effect=[initial,candidate]))
        self.assertEqual((initial,candidate),before);self.assertFalse(r['betting_release'])


    def test_fetch_uses_existing_queries_and_closes(self):
        con=Mock();con.execute.return_value=con
        con.df.side_effect=[self.rows,self.schedule];con.fetchall.return_value=[]
        fake=Mock();fake.connect.return_value=con
        with patch.dict('sys.modules',{'duckdb':fake}):
            out=fetch_snapshot(2027)
        self.assertIs(out[0],self.rows);self.assertIs(out[1],self.schedule)
        con.execute.assert_any_call(LOG_SQL,[2027])
        con.execute.assert_any_call(SCHEDULE_SQL,[2027])
        con.close.assert_called_once()

    def test_fetch_failure_also_closes(self):
        con=Mock();con.execute.side_effect=OSError('offline')
        fake=Mock();fake.connect.return_value=con
        with patch.dict('sys.modules',{'duckdb':fake}):
            with self.assertRaises(OSError):fetch_snapshot(2027)
        con.close.assert_called_once()


    def test_both_missing_home_flags_keep_measurements(self):
        rows=copy.deepcopy(self.rows)
        for row in rows:row['home']=None
        snapshot=self.snapshot(rows);loader=Mock(return_value=snapshot)
        out,r=load_checked(2027,self.now,loader)
        self.assertIs(out,snapshot);loader.assert_called_once()
        self.assertEqual(r['unresolved_game_ids'],[])
        self.assertEqual(r['excluded_home_away_result_game_ids'],['0022600050'])
        self.assertTrue(all(row['home'] is None for row in out[0]))

    def test_archived_0022600189_shape_without_inferred_home(self):
        rows=Frame([{'season':2027,'game_id':'0022600189','game_date':'2026-11-07',
            'team_id':t,'opp_team_id':o,'home':None,'pts':p,
            'off_rating':off,'def_rating':defense,'pace':98.0}
            for t,o,p,off,defense in [('1610612743','1610612754',114,116.3,104.1),
                                     ('1610612754','1610612743',102,104.1,116.3)]])
        for h,a in [('1610612743','1610612754'),('1610612754','1610612743')]:
            s=Frame([{'game_id':'0022600189','game_date':'2026-11-07',
                'home_team_id':h,'away_team_id':a,'status':'final'}])
            out,r=load_checked(2027,self.now,Mock(return_value=self.snapshot(rows,s)))
            self.assertEqual(r['unresolved_game_ids'],[])
            self.assertEqual(r['excluded_home_away_result_game_ids'],['0022600189'])
            self.assertEqual([row['home'] for row in out[0]],[None,None])
            self.assertFalse([row for row in out[0] if row['home'] is True])
            self.assertFalse([row for row in out[0] if row['home'] is False])

    def test_missing_home_flags_do_not_hide_bad_measurements(self):
        rows=copy.deepcopy(self.rows)
        for row in rows:row['home']=None
        rows[0]['off_rating']=0
        _,r=load_checked(2027,self.now,Mock(return_value=self.snapshot(rows)))
        self.assertTrue(r['unresolved_game_ids'])
        self.assertEqual(r['excluded_home_away_result_game_ids'],[])

    def test_missing_home_flags_do_not_hide_wrong_opponents(self):
        rows=copy.deepcopy(self.rows)
        for row in rows:row['home']=None
        rows[0]['opp_team_id']='X'
        _,r=load_checked(2027,self.now,Mock(return_value=self.snapshot(rows)))
        self.assertTrue(r['unresolved_game_ids'])

    def test_contradictory_known_home_flag_stays_blocked(self):
        rows=copy.deepcopy(self.rows);rows[0]['home']=False
        _,r=load_checked(2027,self.now,Mock(return_value=self.snapshot(rows)))
        self.assertTrue(r['unresolved_game_ids'])

    def test_recovered_snapshot_records_pair_exclusion(self):
        rows=copy.deepcopy(self.rows)
        for row in rows:row['home']=None
        first=self.snapshot(Frame());candidate=self.snapshot(rows)
        out,r=load_checked(2027,self.now,Mock(side_effect=[first,candidate]))
        self.assertIs(out,candidate)
        self.assertEqual(r['status'],'recovered')
        self.assertEqual(r['excluded_home_away_result_game_ids'],['0022600050'])


if __name__=='__main__':unittest.main()
