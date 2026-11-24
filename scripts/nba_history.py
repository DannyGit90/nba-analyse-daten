"""Automatic team-history backfill before the existing full-store collector."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo

FIRST_SEASON = 2010


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def validate_closed_season(values, season, today):
    if not values or len(values)>200000:
        raise ValueError('Empty or oversized closed season: '+str(season))
    games={};keys=set();teams=set()
    for r in values:
        key=(r['game_id'],r['team_id'])
        if key in keys or r['season']!=season or not re.fullmatch(r'002\d{7}',r['game_id']):
            raise ValueError('Invalid or duplicate historical game key: '+str(season))
        keys.add(key)
        for field in ('team_id','opp_team_id'):
            if not isinstance(r[field],str) or not r[field].strip():
                raise ValueError('Invalid historical team ID')
        date=dt.date.fromisoformat(r['game_date'])
        if date>today or type(r['pts']) not in (int,float) or not math.isfinite(r['pts']) or r['pts']<0 or not float(r['pts']).is_integer():
            raise ValueError('Invalid historical date or score')
        teams.add(r['team_id']);games.setdefault(r['game_id'],[]).append(r)
    if len(teams)!=30:
        raise ValueError('Closed season does not cover 30 teams: '+str(season))
    for pair in games.values():
        if len(pair)!=2:
            raise ValueError('Incomplete historical game pair')
        a,b=pair
        if a['team_id']!=b['opp_team_id'] or b['team_id']!=a['opp_team_id'] or a['team_id']==b['team_id'] or a['game_date']!=b['game_date'] or a['pts']==b['pts']:
            raise ValueError('Conflicting historical game pair')
    return {'season':season,'rows':len(values),'games':len(games),'teams':len(teams)}


def extend_history(data, fetch, now):
    if now.tzinfo is None:
        raise ValueError('Aware clock required')
    today=now.astimezone(ZoneInfo('America/New_York')).date()
    current=today.year+int(today.month>=10)
    result=dict(data);proofs=[];fetched=[]
    for year in range(FIRST_SEASON,current):
        name=f'team_game_logs/season={year}.jsonl'
        if name not in result:
            result[name]=fetch(year);fetched.append(year)
        proof=validate_closed_season(result[name],year,today)
        proof['reused']=year not in fetched;proofs.append(proof)
    return result,{'first_season':FIRST_SEASON,'current_season':current,'fetched_seasons':fetched,'closed_season_checks':proofs}


def write_stage(data, manifest, destination, history):
    path=Path(destination)
    if path.exists():
        raise ValueError('Fresh history staging path required')
    contents={};tables={}
    for name,values in data.items():
        if not re.fullmatch(r'(players|[a-z_]+/season=\d{4})\.jsonl',name):
            raise ValueError('Unsafe history table path')
        body=''.join(canonical(r)+'\n' for r in values).encode()
        if len(body)>20000000:
            raise ValueError('History table exceeds existing 20 MB limit')
        contents[name]=body;tables[name]={'rows':len(values),'sha256':hashlib.sha256(body).hexdigest()}
    if sum(map(len,contents.values()))>100000000:
        raise ValueError('History exceeds existing 100 MB limit')
    updated=dict(manifest,tables=tables,history_backfill=history)
    path.mkdir(parents=True)
    for name,body in contents.items():
        target=path/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
    (path/'manifest.json').write_text(canonical(updated)+'\n')
    return updated


def compact_status(report, previous_manifest_sha256, history=None):
    tables=report.get('tables',{})
    seasons=sorted(int(n.split('=')[1].split('.')[0]) for n in tables if n.startswith('team_game_logs/season='))
    quality=report.get('diagnostics',{}).get('catalog_quality',{})
    changes=report.get('changes',{})
    return {'schema':'nba-store-status-v1','execution_ok':report.get('execution_ok') is True,
        'run_id':report.get('run_id') or os.environ.get('NBA_STORE_RUN_ID'),
        'observed_at_utc':report.get('observed_at_utc'),'code_sha':report.get('code_sha'),
        'previous_manifest_sha256':previous_manifest_sha256,
        'table_count':len(tables),'table_rows':{k:v['rows'] for k,v in tables.items()},
        'team_history_seasons':seasons,'roster_date':report.get('roster_date'),
        'roster_team_count':report.get('roster_team_count'),'roster_player_count':report.get('roster_player_count'),
        'catalog_rows':quality.get('rows'),'unusable_name_rows':quality.get('unusable_name_rows'),
        'new_source_player_count':len(changes.get('new_source_player_ids',[])),
        'observed_roster_change_count':len(changes.get('roster_changes',[])),
        'source_metadata':report.get('source_metadata',[]),'error':report.get('error'),
        'diagnostic_stage':report.get('diagnostics',{}).get('stage'),
        'history_stage_ok':(history or {}).get('history_stage_ok'),
        'history_fetched_seasons':(history or {}).get('history',{}).get('fetched_seasons',[]),
        'model_input_approved':False,'betting_release':False}


def main():
    from nba_store import read_store, rows, prepare
    p=argparse.ArgumentParser()
    p.add_argument('--source-root',default='data/nba')
    p.add_argument('--stage-root',required=True)
    p.add_argument('--report',required=True)
    a=p.parse_args();now=dt.datetime.now(dt.timezone.utc)
    report={'schema':'nba-history-stage-v1','execution_ok':False,'history_stage_ok':False,
        'observed_at_utc':now.isoformat(),'betting_release':False,'saved_store_modified':False}
    con=None
    try:
        import duckdb
        con=duckdb.connect()
        con.execute("ATTACH 'https://basketball-data.billmill.org/nba/nba.duckdb' AS nba (READ_ONLY)")
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(a.source_root)
            manifest,data=read_store(source)
            if not manifest:
                source=Path(temporary)/'base'
                prepare(a.source_root,source,con,now,os.environ['NBA_STORE_RUN_ID']+'_base',os.environ['NBA_STORE_CODE_SHA'])
                manifest,data=read_store(source)
            def fetch(year):
                return rows(con,"SELECT * FROM nba.main.team_game_logs WHERE season=? AND game_id LIKE '002%' ORDER BY game_id,team_id",[year])
            data,proof=extend_history(data,fetch,now)
            write_stage(data,manifest,a.stage_root,proof)
            read_store(a.stage_root)
            report.update(history_stage_ok=True,history=proof,error='Final full-store collection has not completed yet')
    except Exception as exc:
        report['error']=(type(exc).__name__+': '+str(exc))[:800]
    finally:
        if con is not None:con.close()
    target=Path(a.report);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(canonical(report)+'\n')
    raise SystemExit(0 if report['history_stage_ok'] else 1)


if __name__=='__main__':main()
