import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from local_model_run import inspect_report,execute_isolated,blob,sha,protected_state

NOW=dt.datetime(2026,11,24,20,tzinfo=dt.timezone.utc)
def valid_report(pin='a'*64):
    return dict(execution_ok=True,protocol='season-prior10-paper-v1',prior_strength=10,ridge_alpha=100.0,
        money_betting_released=False,production_model_changed=False,generated_at_utc=NOW.isoformat(),
        data_refresh=dict(source='local:nba-source-store',source_mode='local_frozen_snapshot',read_attempts=1,unresolved_game_ids=[],
          source_evidence=dict(manifest_sha256=pin,external_access_enabled=False,saved_store_modified=False,model_input_approved=False,betting_release=False)),
        completed_schedule_games_missing_from_logs=[],training_games=500,residual_n=200,
        training_latest_game='2026-10-31',feature_data_latest_game='2026-11-23',skipped_games=[],
        forecasts=[dict(game_id='0022600001',start_time_utc=(NOW+dt.timedelta(hours=2)).isoformat(),
          p_home_experimental=0.6,p_away_experimental=0.4,home_margin_point=2.0,total_point=220.0,betting_release=False)])

class ReportTests(unittest.TestCase):
    def check(self,r,pin='a'*64):return inspect_report(r,pin,NOW-dt.timedelta(seconds=1),NOW+dt.timedelta(seconds=1))
    def test_full_report_passes_without_release(self):
        r=self.check(valid_report());self.assertTrue(r['acceptance_passed']);self.assertFalse(r['model_input_approved'])
    def test_changed_pin_blocked(self):
        with self.assertRaisesRegex(ValueError,'another snapshot'):self.check(valid_report(),'b'*64)
    def test_stale_report_blocked(self):
        r=valid_report();r['generated_at_utc']=(NOW-dt.timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError,'not from this execution'):self.check(r)
    def test_changed_parameters_blocked(self):
        r=valid_report();r['ridge_alpha']=99.0
        with self.assertRaisesRegex(ValueError,'parameters'):self.check(r)
    def test_incomplete_source_blocked(self):
        r=valid_report();r['data_refresh']['unresolved_game_ids']=['missing']
        with self.assertRaisesRegex(ValueError,'Incomplete'):self.check(r)
    def test_release_blocked(self):
        r=valid_report();r['money_betting_released']=True
        with self.assertRaisesRegex(ValueError,'release'):self.check(r)
    def test_bad_forecast_number_blocked(self):
        r=valid_report();r['forecasts'][0]['total_point']=float('nan')
        with self.assertRaisesRegex(ValueError,'number'):self.check(r)
    def test_started_forecast_blocked(self):
        r=valid_report();r['forecasts'][0]['start_time_utc']=NOW.isoformat()
        with self.assertRaisesRegex(ValueError,'pregame'):self.check(r)
    def test_no_forecasts_not_claimed_verified(self):
        r=valid_report();r['forecasts']=[];out=self.check(r)
        self.assertFalse(out['acceptance_passed']);self.assertEqual(out['status'],'model_executed_without_forecasts')
    def test_future_training_date_blocked(self):
        r=valid_report();r['training_latest_game']='2026-11-01'
        with self.assertRaisesRegex(ValueError,'Nonhistorical'):self.check(r)

class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.root=self.base/'checkout'
        for name in ('scripts','reports','paper_log','data/nba'):(self.root/name).mkdir(parents=True,exist_ok=True)
        self.core=b'pass\n'
        for name in ('paper_monitor.py','paper_data_refresh.py','local_model_source.py'):(self.root/'scripts'/name).write_bytes(self.core)
        (self.root/'reports/season_prior_test.json').write_text('{}')
        (self.root/'reports/paper_latest.json').write_text('{"old":true}')
        (self.root/'reports/paper_evaluation.json').write_text('{"old":true}')
        (self.root/'paper_log/old.json').write_text('{}')
        (self.root/'data/nba/manifest.json').write_text('{}')
    def fake_model(self,command,**kwargs):
        cwd=Path(kwargs['cwd']);env=kwargs['env']
        self.assertNotEqual(cwd,self.root);self.assertEqual(command[1],'scripts/paper_monitor.py')
        self.assertFalse((cwd/'reports/paper_latest.json').exists())
        self.assertTrue((cwd/'reports/season_prior_test.json').exists());self.assertTrue((cwd/'paper_log/old.json').exists())
        self.assertEqual(env['NBA_STORE_ROOT'],str(self.root/'data/nba'))
        self.assertEqual(env['NBA_STORE_MANIFEST_SHA256'],sha(b'{}'))
        (cwd/'reports/paper_latest.json').write_text(json.dumps(valid_report(env['NBA_STORE_MANIFEST_SHA256'])))
        (cwd/'paper_log/new.json').write_text('{}')
        return SimpleNamespace(returncode=0,stderr='')
    def run_check(self,process=None,**extra):
        return execute_isolated(self.root,self.base/'output',process=process or self.fake_model,clock=lambda:NOW,expected_model_blob=blob(self.core),**extra)
    def test_isolation_and_persistence(self):
        before=protected_state(self.root);r=self.run_check()
        self.assertTrue(r['execution_ok']);self.assertTrue(r['canonical_inputs_unchanged'])
        self.assertEqual(before,protected_state(self.root));self.assertFalse((self.root/'paper_log/new.json').exists())
        self.assertTrue((self.base/'output/model_report.json').exists());self.assertTrue((self.base/'output/acceptance.json').exists())
    def test_nonzero_process_exit_blocked(self):
        r=self.run_check(process=lambda *a,**k:SimpleNamespace(returncode=1,stderr='failed'))
        self.assertFalse(r['execution_ok']);self.assertIn('subprocess',r['error'])
    def test_exit_zero_does_not_hide_model_failure(self):
        def failed(command,**kwargs):
            (Path(kwargs['cwd'])/'reports/paper_latest.json').write_text(json.dumps({'execution_ok':False,'error':'synthetic failure'}))
            return SimpleNamespace(returncode=0,stderr='')
        r=self.run_check(failed);self.assertFalse(r['execution_ok']);self.assertIn('Model execution failed',r['error'])
    def test_changed_core_bytes_blocked(self):
        (self.root/'scripts/paper_monitor.py').write_text('changed')
        r=self.run_check();self.assertFalse(r['execution_ok']);self.assertIn('Core model bytes',r['error'])
    def test_canonical_mutation_detected(self):
        def mutating(command,**kwargs):
            result=self.fake_model(command,**kwargs);(self.root/'reports/paper_latest.json').write_text('{}');return result
        r=self.run_check(mutating);self.assertFalse(r['execution_ok']);self.assertFalse(r['canonical_inputs_unchanged'])
    def test_output_inside_checkout_rejected(self):
        with self.assertRaisesRegex(ValueError,'outside'):execute_isolated(self.root,self.root/'output')
    def test_real_subprocess_startup_in_temporary_scripts_directory(self):
        source="""import datetime as dt,json,os
from pathlib import Path
import paper_data_refresh,local_model_source
now=dt.datetime.now(dt.timezone.utc);day=now.date()
r={'execution_ok':True,'protocol':'season-prior10-paper-v1','prior_strength':10,'ridge_alpha':100.0,'money_betting_released':False,'production_model_changed':False,'generated_at_utc':now.isoformat(),'data_refresh':{'source':'local:nba-source-store','source_mode':'local_frozen_snapshot','read_attempts':1,'unresolved_game_ids':[],'source_evidence':{'manifest_sha256':os.environ['NBA_STORE_MANIFEST_SHA256'],'external_access_enabled':False,'saved_store_modified':False,'model_input_approved':False,'betting_release':False}},'completed_schedule_games_missing_from_logs':[],'training_games':500,'residual_n':200,'training_latest_game':(day.replace(day=1)-dt.timedelta(days=1)).isoformat(),'feature_data_latest_game':(day-dt.timedelta(days=1)).isoformat(),'skipped_games':[],'forecasts':[{'game_id':'0022600001','start_time_utc':(now+dt.timedelta(hours=1)).isoformat(),'p_home_experimental':0.6,'p_away_experimental':0.4,'home_margin_point':2.0,'total_point':220.0,'betting_release':False}]}
Path('reports/paper_latest.json').write_text(json.dumps(r))
"""
        (self.root/'scripts/paper_monitor.py').write_text(source)
        r=execute_isolated(self.root,self.base/'output',expected_model_blob=blob(source.encode()))
        self.assertTrue(r['execution_ok'],r);self.assertTrue(r['canonical_inputs_unchanged'])
if __name__=='__main__':unittest.main()
