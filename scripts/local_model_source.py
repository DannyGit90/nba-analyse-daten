"""Read-only local model-input loader; not activated in the production pipeline."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re

LOG_SQL = "SELECT season, game_id, team_id, opp_team_id, game_date, home, pts, off_rating, def_rating, pace FROM nba.team_game_logs WHERE season BETWEEN 2010 AND ? AND CAST(game_id AS VARCHAR) LIKE '002%'"
SCHEDULE_SQL = "SELECT game_id, game_date, start_time, home_team_id, away_team_id, neutral_site, status FROM nba.schedule WHERE season = ? AND CAST(game_id AS VARCHAR) LIKE '002%'"
COLUMNS={
 'team_game_logs':{'season':'INTEGER','game_id':'VARCHAR','team_id':'VARCHAR','opp_team_id':'VARCHAR','game_date':'DATE','home':'BOOLEAN','pts':'INTEGER','off_rating':'DOUBLE','def_rating':'DOUBLE','pace':'DOUBLE'},
 'schedule':{'season':'INTEGER','game_id':'VARCHAR','game_date':'DATE','start_time':'TIMESTAMPTZ','home_team_id':'VARCHAR','away_team_id':'VARCHAR','neutral_site':'BOOLEAN','status':'VARCHAR'},
 'team_seasons':{'season':'INTEGER','team_id':'VARCHAR','nba_abbrev':'VARCHAR','is_nba':'BOOLEAN'}}


def sha(body):return hashlib.sha256(body).hexdigest()


def stamp(text):
    t=dt.datetime.fromisoformat(text.replace('Z','+00:00'))
    if t.tzinfo is None or t.utcoffset() is None:raise ValueError('Aware timestamp required')
    return t


def typed(v,kind,field):
    if v is None:return None
    if kind=='VARCHAR' and not isinstance(v,str):raise ValueError('String required: '+field)
    if field.endswith('_id') and isinstance(v,str) and not v.strip():raise ValueError('Empty ID')
    if kind=='INTEGER' and type(v) is not int:raise ValueError('Integer required without coercion: '+field)
    if kind=='BOOLEAN' and type(v) is not bool:raise ValueError('Boolean required: '+field)
    if kind=='DOUBLE' and (type(v) not in (int,float) or not math.isfinite(v)):raise ValueError('Finite measurement required')
    if kind=='DATE':return dt.date.fromisoformat(v)
    if kind=='TIMESTAMPTZ':return stamp(v)
    return v


def fetch_local_snapshot(season,root,now,manifest_sha256):
    """Return legacy (logs DataFrame, schedule DataFrame, team tuples).

    Both frames carry nba_store_evidence in attrs. No saved files are changed.
    Explicit pin, complete team history and accepted source times are required.
    """
    if type(season) is not int or not 2010<=season<=2100:raise ValueError('Invalid season')
    if now.tzinfo is None:raise ValueError('Aware clock required')
    if not isinstance(manifest_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',manifest_sha256):raise ValueError('Explicit SHA256 pin required')
    root=Path(root).resolve();mf=root/'manifest.json'
    if mf.is_symlink() or mf.stat().st_size>2000000:raise ValueError('Invalid manifest file')
    body=mf.read_bytes()
    if sha(body)!=manifest_sha256:raise ValueError('Snapshot pin mismatch')
    m=json.loads(body)
    if m.get('schema')!='nba-source-store-v1' or m.get('execution_ok') is not True or m.get('season')!=season:raise ValueError('Accepted matching store required')
    if m.get('betting_release') is not False or m.get('model_input_approved') is not False:raise ValueError('Unexpected release')
    observed=stamp(m['observed_at_utc'])
    if not now-dt.timedelta(hours=8)<=observed<=now:raise ValueError('Stale or future snapshot')
    metadata=m.get('source_metadata',[])
    expected={'team_seasons','rosters_daily','schedule','team_game_logs','player_game_logs'}
    if len(metadata)!=5 or {r.get('dataset') for r in metadata}!=expected:raise ValueError('Incomplete source metadata')
    if any(not now-dt.timedelta(hours=72)<=stamp(r['updated'])<=observed for r in metadata):raise ValueError('Stale or future source metadata')
    needed={f'team_game_logs/season={y}.jsonl' for y in range(2010,season+1)}|{f'schedule/season={season}.jsonl',f'team_seasons/season={season}.jsonl'}
    missing=sorted(needed-set(m['tables']))
    if missing:raise ValueError('Missing required partitions: '+', '.join(missing))
    selected={};total=0
    for name,proof in sorted(m['tables'].items()):
        if not re.fullmatch(r'(players|[a-z_]+/season=\d{4})\.jsonl',name):raise ValueError('Unsafe table path')
        path=root/name
        if not path.resolve().is_relative_to(root) or path.is_symlink() or path.stat().st_size>20000000:raise ValueError('Unsafe or oversized table')
        content=path.read_bytes();total+=len(content)
        if total>100000000 or sha(content)!=proof['sha256']:raise ValueError('Table hash or store size mismatch')
        lines=content.splitlines()
        if len(lines)!=proof['rows'] or len(lines)>200000:raise ValueError('Table row count mismatch')
        if name in needed:
            rows=[json.loads(line) for line in lines]
            if not rows and name.startswith('team_game_logs/') and name!=f'team_game_logs/season={season}.jsonl':raise ValueError('Empty required historical season')
            selected[name]=rows
    if mf.read_bytes()!=body:raise ValueError('Manifest changed during read')
    import duckdb
    con=duckdb.connect()
    try:
        con.execute("ATTACH ':memory:' AS nba")
        con.execute('SET enable_external_access=false')
        for table,columns in COLUMNS.items():
            fields=list(columns);records=[];seen=set()
            for name,values in selected.items():
                if not name.startswith(table+'/'):continue
                year=int(name.split('=')[1].split('.')[0])
                for row in values:
                    if not set(fields)<=set(row):raise ValueError('Missing columns: '+table)
                    r={k:typed(row[k],t,k) for k,t in columns.items()}
                    if r['season']!=year:raise ValueError('Partition season mismatch')
                    keys=('season','game_id','team_id') if table=='team_game_logs' else ('season','game_id') if table=='schedule' else ('season','team_id')
                    key=tuple(r[k] for k in keys)
                    if None in key or key in seen:raise ValueError('Missing or duplicate key: '+table)
                    seen.add(key);records.append(tuple(r[k] for k in fields))
            con.execute('CREATE TABLE nba.main.'+table+' ('+','.join('"'+k+'" '+t for k,t in columns.items())+')')
            if records:con.executemany('INSERT INTO nba.main.'+table+' VALUES ('+','.join('?' for _ in fields)+')',records)
        data=con.execute(LOG_SQL,[season]).df()
        schedule=con.execute(SCHEDULE_SQL,[season]).df()
        teams=con.execute('SELECT team_id, nba_abbrev FROM nba.team_seasons WHERE season = ? AND is_nba = true',[season]).fetchall()
        proof={'schema':'local-model-source-v1','manifest_sha256':manifest_sha256,'store_run_id':m['run_id'],
            'store_observed_at_utc':m['observed_at_utc'],'source_metadata':metadata,'history_first_season':2010,'history_last_season':season,
            'model_log_rows':len(data),'model_schedule_rows':len(schedule),'team_mapping_rows':len(teams),
            'external_access_enabled':bool(con.execute("SELECT current_setting('enable_external_access')").fetchone()[0]),
            'saved_store_modified':False,'historical_publication_verified':False,'model_input_approved':False,'betting_release':False}
        data.attrs['nba_store_evidence']=proof;schedule.attrs['nba_store_evidence']=dict(proof)
        return data,schedule,teams
    finally:
        con.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='data/nba');p.add_argument('--report',required=True);a=p.parse_args()
    now=dt.datetime.now(dt.timezone.utc)
    result={'execution_ok':False,'schema':'local-model-source-check-v1','code_sha':os.environ.get('GITHUB_SHA'),'checked_at_utc':now.isoformat(),'betting_release':False}
    try:
        body=(Path(a.root)/'manifest.json').read_bytes();season=json.loads(body)['season']
        data,schedule,teams=fetch_local_snapshot(season,a.root,now,sha(body))
        result.update(execution_ok=True,source_evidence=data.attrs['nba_store_evidence'],null_home_rows=int(data.home.isna().sum()))
    except Exception as exc:
        result['error']=(type(exc).__name__+': '+str(exc))[:800]
    path=Path(a.report);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    raise SystemExit(0 if result['execution_ok'] else 1)


if __name__=='__main__':main()
