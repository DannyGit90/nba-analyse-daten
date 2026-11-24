import copy
import datetime as dt
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import paper_data_refresh as refresh

class Frame(list):
    def to_dict(self,orient):return copy.deepcopy(list(self))

class LocalDefaultTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,24,20,tzinfo=dt.timezone.utc)
        self.rows=Frame([dict(season=2027,game_id='0022600001',game_date='2026-11-22',team_id=t,opp_team_id=o,home=h,pts=p,off_rating=110.0,def_rating=105.0,pace=98.0) for t,o,h,p in [('H','A',True,100),('A','H',False,90)]])
        self.rows.attrs={'nba_store_evidence':dict(schema='local-model-source-v1',manifest_sha256='a'*64,store_run_id='saved',external_access_enabled=False,saved_store_modified=False,model_input_approved=False,betting_release=False)}
        self.schedule=Frame([dict(game_id='0022600001',game_date='2026-11-22',home_team_id='H',away_team_id='A',status='final')])
        self.snapshot=(self.rows,self.schedule,[('H','HOME'),('A','AWAY')])
    def test_default_uses_local_source_and_forwards_proof(self):
        with patch.object(refresh,'fetch_store_snapshot',return_value=self.snapshot) as local,patch.object(refresh,'fetch_snapshot',side_effect=AssertionError('network')) as remote:
            out,r=refresh.load_checked(2027,self.now)
        local.assert_called_once_with(2027,self.now);remote.assert_not_called();self.assertIs(out,self.snapshot)
        self.assertEqual(r['source'],'local:nba-source-store');self.assertEqual(r['source_evidence']['store_run_id'],'saved')
        self.rows.attrs['nba_store_evidence']['store_run_id']='changed'
        self.assertEqual(r['source_evidence']['store_run_id'],'saved')
    def test_local_failure_never_falls_back(self):
        with patch.object(refresh,'fetch_store_snapshot',side_effect=OSError('missing local file')),patch.object(refresh,'fetch_snapshot') as remote:
            with self.assertRaises(OSError):refresh.load_checked(2027,self.now)
        remote.assert_not_called()
    def test_local_gap_remains_open_without_reloading_same_snapshot(self):
        self.rows.pop()
        with patch.object(refresh,'fetch_store_snapshot',return_value=self.snapshot) as local,patch.object(refresh,'fetch_snapshot') as remote:
            out,r=refresh.load_checked(2027,self.now)
        local.assert_called_once();remote.assert_not_called();self.assertIs(out,self.snapshot)
        self.assertEqual(r['read_attempts'],1);self.assertEqual(r['status'],'local_snapshot_incomplete')
        self.assertEqual(r['unresolved_game_ids'],['0022600001']);self.assertFalse(r['betting_release'])
    def test_missing_provenance_blocks_default(self):
        self.rows.attrs={}
        with patch.object(refresh,'fetch_store_snapshot',return_value=self.snapshot):
            with self.assertRaisesRegex(ValueError,'evidence required'):refresh.load_checked(2027,self.now)
    def test_explicit_test_loader_keeps_bounded_retry(self):
        incomplete=(Frame(),self.schedule,self.snapshot[2]);loader=Mock(side_effect=[incomplete,self.snapshot])
        with patch.object(refresh,'fetch_store_snapshot',side_effect=AssertionError('must not read store')):
            out,r=refresh.load_checked(2027,self.now,loader)
        self.assertEqual(loader.call_count,2);self.assertIs(out,self.snapshot);self.assertEqual(r['status'],'recovered')
    def test_store_call_freezes_actual_manifest_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            body=b'{"fixture":true}';(Path(folder)/'manifest.json').write_bytes(body)
            fake=Mock();fake.fetch_local_snapshot.return_value=self.snapshot
            with patch.dict(os.environ,{'NBA_STORE_ROOT':folder},clear=True),patch.dict('sys.modules',{'local_model_source':fake}):
                self.assertIs(refresh.fetch_store_snapshot(2027,self.now),self.snapshot)
            fake.fetch_local_snapshot.assert_called_once_with(2027,Path(folder),self.now,hashlib.sha256(body).hexdigest())
    def test_explicit_pin_is_preserved(self):
        fake=Mock();fake.fetch_local_snapshot.return_value=self.snapshot
        with patch.dict(os.environ,{'NBA_STORE_ROOT':'fixture-root','NBA_STORE_MANIFEST_SHA256':'b'*64},clear=True),patch.dict('sys.modules',{'local_model_source':fake}):
            refresh.fetch_store_snapshot(2027,self.now)
        self.assertEqual(fake.fetch_local_snapshot.call_args.args[-1],'b'*64)
    def test_both_missing_home_flags_remain_null(self):
        for row in self.rows:row['home']=None
        with patch.object(refresh,'fetch_store_snapshot',return_value=self.snapshot):out,r=refresh.load_checked(2027,self.now)
        self.assertEqual(r['unresolved_game_ids'],[]);self.assertEqual(r['excluded_home_away_result_game_ids'],['0022600001'])
        self.assertTrue(all(row['home'] is None for row in out[0]))
if __name__=='__main__':unittest.main()
