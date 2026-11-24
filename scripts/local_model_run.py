"""Isolated execution acceptance for the unchanged paper model; no canonical writes."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

MODEL_BLOB='e328db54b76dd2ec718e840a847d11873a8bb07e'


def sha(body):return hashlib.sha256(body).hexdigest()


def blob(body):return hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()


def stamp(text):
    value=dt.datetime.fromisoformat(text.replace('Z','+00:00'))
    if value.tzinfo is None or value.utcoffset() is None:raise ValueError('Aware timestamp required')
    return value


def protected_state(root):
    paths=list((root/'data'/'nba').rglob('*'))+list((root/'paper_log').glob('*.json'))
    paths += [root/'reports'/'paper_latest.json',root/'reports'/'paper_evaluation.json']
    result={};total=0
    for path in sorted(paths):
        if not path.exists():continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('Unsafe protected path')
        if not path.is_file():continue
        total+=path.stat().st_size
        if total>200000000:raise ValueError('Acceptance input budget exceeded; no truncation')
        result[path.relative_to(root).as_posix()]=sha(path.read_bytes())
    return result


def inspect_report(report,pin,started,finished):
    if report.get('execution_ok') is not True:raise ValueError('Model execution failed: '+str(report.get('error','unknown'))[:400])
    if report.get('protocol')!='season-prior10-paper-v1' or report.get('prior_strength')!=10 or report.get('ridge_alpha')!=100.0:
        raise ValueError('Unexpected model protocol or parameters')
    if report.get('money_betting_released') is not False or report.get('production_model_changed') is not False:raise ValueError('Unexpected release or model-change flag')
    generated=stamp(report['generated_at_utc'])
    if not started<=generated<=finished:raise ValueError('Model report is not from this execution')
    refresh=report.get('data_refresh',{});evidence=refresh.get('source_evidence',{})
    if refresh.get('source')!='local:nba-source-store' or refresh.get('source_mode')!='local_frozen_snapshot' or refresh.get('read_attempts')!=1:
        raise ValueError('Standard local model path not proven')
    if evidence.get('manifest_sha256')!=pin:raise ValueError('Model used another snapshot')
    if any(evidence.get(k) is not False for k in ('external_access_enabled','saved_store_modified','model_input_approved','betting_release')):
        raise ValueError('Invalid source evidence flags')
    if refresh.get('unresolved_game_ids')!=[] or report.get('completed_schedule_games_missing_from_logs')!=[]:
        raise ValueError('Incomplete local game source')
    day=generated.astimezone(dt.timezone.utc).date()
    if dt.date.fromisoformat(report['feature_data_latest_game'])>=day or dt.date.fromisoformat(report['training_latest_game'])>=day.replace(day=1):
        raise ValueError('Nonhistorical model feature or training date')
    if type(report.get('training_games')) is not int or report['training_games']<500 or type(report.get('residual_n')) is not int or report['residual_n']<200:
        raise ValueError('Existing internal training prerequisites not proven')
    forecasts=report.get('forecasts');seen=set()
    if not isinstance(forecasts,list):raise ValueError('Forecast list required')
    for f in forecasts:
        gid=f.get('game_id')
        if not isinstance(gid,str) or not re.fullmatch(r'002\d{7}',gid) or gid in seen:raise ValueError('Invalid or duplicate forecast identity')
        seen.add(gid)
        if not generated<stamp(f['start_time_utc'])<=generated+dt.timedelta(hours=24):raise ValueError('Forecast is not in the pregame window')
        if f.get('betting_release') is not False or f.get('recommendation') is not None:raise ValueError('Unexpected recommendation')
        for key in ('p_home_experimental','p_away_experimental','home_margin_point','total_point'):
            v=f[key]
            if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('Invalid forecast number')
            if key.startswith('p_') and not 0<=v<=1:raise ValueError('Invalid probability')
    return {'forecast_generation_verified':bool(forecasts),'acceptance_passed':bool(forecasts),
        'status':'passed_with_forecasts' if forecasts else 'model_executed_without_forecasts',
        'forecast_count':len(forecasts),'skipped_game_count':len(report.get('skipped_games',[])),
        'training_games':report['training_games'],'training_latest_game':report.get('training_latest_game'),
        'feature_data_latest_game':report.get('feature_data_latest_game'),'residual_n':report['residual_n'],
        'source_evidence':evidence,'model_input_approved':False,'betting_release':False}


def execute_isolated(root,output,process=None,clock=None,expected_model_blob=MODEL_BLOB):
    root=Path(root).resolve();output=Path(output).resolve()
    if output.is_relative_to(root):raise ValueError('Acceptance output must be outside the source checkout')
    if output.exists():raise ValueError('Fresh acceptance output directory required')
    output.mkdir(parents=True)
    process=process or subprocess.run;clock=clock or (lambda:dt.datetime.now(dt.timezone.utc))
    result={'schema':'local-model-run-v1','execution_ok':False,'acceptance_passed':False,
            'code_sha':os.environ.get('GITHUB_SHA'),'betting_release':False,
            'scope':'Isolated unchanged-model execution, not pricing, personnel, calibration or profitability validation'}
    before=None;report=None
    try:
        before=protected_state(root)
        model=(root/'scripts'/'paper_monitor.py').read_bytes()
        if blob(model)!=expected_model_blob:raise ValueError('Core model bytes differ from the reviewed model')
        mf=root/'data'/'nba'/'manifest.json';pin=sha(mf.read_bytes())
        result.update(model_blob=blob(model),manifest_sha256=pin)
        with tempfile.TemporaryDirectory() as temporary:
            sandbox=Path(temporary);(sandbox/'scripts').mkdir();(sandbox/'reports').mkdir();(sandbox/'paper_log').mkdir()
            for name in ('paper_monitor.py','paper_data_refresh.py','local_model_source.py'):
                source=root/'scripts'/name
                if source.is_symlink() or not source.resolve().is_relative_to(root):raise ValueError('Unsafe script path')
                shutil.copyfile(source,sandbox/'scripts'/name)
            if blob((sandbox/'scripts'/'paper_monitor.py').read_bytes())!=blob(model):raise ValueError('Model copy differs')
            audit=root/'reports'/'season_prior_test.json'
            if audit.is_symlink() or not audit.resolve().is_relative_to(root) or audit.stat().st_size>2000000:raise ValueError('Invalid model audit file')
            shutil.copyfile(audit,sandbox/'reports'/'season_prior_test.json')
            for source in (root/'paper_log').glob('*.json'):
                shutil.copyfile(source,sandbox/'paper_log'/source.name)
            env=dict(os.environ,NBA_STORE_ROOT=str(root/'data'/'nba'),NBA_STORE_MANIFEST_SHA256=pin,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
            env.pop('PYTHONPATH',None)
            started=clock();result['started_at_utc']=started.isoformat()
            completed=process([sys.executable,'scripts/paper_monitor.py'],cwd=sandbox,env=env,capture_output=True,text=True,timeout=480)
            finished=clock();result['finished_at_utc']=finished.isoformat();result['model_exit_code']=completed.returncode
            produced=sandbox/'reports'/'paper_latest.json'
            if produced.exists():
                if produced.stat().st_size>2000000:raise ValueError('Model report too large')
                report=json.loads(produced.read_text())
            if completed.returncode!=0:raise ValueError('Model subprocess failed: '+str(completed.stderr)[-800:])
            if not isinstance(report,dict):raise ValueError('No fresh model report generated')
            result.update(inspect_report(report,pin,started,finished),execution_ok=True)
    except Exception as exc:
        result['error']=(type(exc).__name__+': '+str(exc))[:1000]
    finally:
        if before is not None:
            try:unchanged=protected_state(root)==before
            except Exception:unchanged=False
            result['canonical_inputs_unchanged']=unchanged
            if not unchanged:result.update(execution_ok=False,acceptance_passed=False,error='Canonical inputs changed during acceptance')
        if isinstance(report,dict):
            try:(output/'model_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
            except (ValueError,TypeError) as exc:result.update(execution_ok=False,acceptance_passed=False,error='Invalid model report serialization: '+str(exc)[:300])
        (output/'acceptance.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--output',required=True);a=p.parse_args()
    r=execute_isolated(a.root,a.output)
    raise SystemExit(0 if r['execution_ok'] else 1)


if __name__=='__main__':main()
