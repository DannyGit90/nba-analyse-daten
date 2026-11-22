"""Observed recent player contributions; no inferred availability or impact."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from team_analysis import stamp

SOURCE = 'https://basketball-data.billmill.org/nba/nba.duckdb'
FIELDS = ('pts','fga','fg3a','ast','reb')


def rows(con, sql, params):
    cursor = con.execute(sql,params)
    return [dict(zip([c[0] for c in cursor.description],r)) for r in cursor.fetchall()]


def summarize(records, game_ids, team_id, cutoff):
    if not game_ids or len(game_ids)>10 or len(game_ids)!=len(set(game_ids)):
        raise ValueError('Invalid selected team games')
    if not records or len(records)>1000:
        raise ValueError('Empty or oversized player records')
    grouped,seen = {},set()
    for r in records:
        if r['team_id']!=team_id or r['game_id'] not in game_ids or not isinstance(r['player_id'],str) or not r['player_id'].strip():
            raise ValueError('Invalid player or team identity')
        if not isinstance(r['game_date'],dt.date) or isinstance(r['game_date'],dt.datetime) or r['game_date']>=cutoff:
            raise ValueError('Invalid or nonhistorical game date')
        key = (r['game_id'],r['player_id'],r['team_id'])
        if key in seen:
            raise ValueError('Duplicate player game record')
        seen.add(key)
        for k in FIELDS:
            if type(r[k]) is not int or r[k]<0:
                raise ValueError('Invalid counting stat: '+k)
        if r['fg3a']>r['fga']:
            raise ValueError('Three-point attempts exceed field-goal attempts')
        grouped.setdefault(r['player_id'],[]).append(r)
    if {r['game_id'] for r in records}!=set(game_ids):
        raise ValueError('Selected game missing player logs')
    result = []
    for pid,values in sorted(grouped.items()):
        result.append({'player_id':pid,'observed_records':len(values),
            'latest_game_date':max(r['game_date'] for r in values).isoformat(),
            'mean_per_record':{k:sum(r[k] for r in values)/len(values) for k in FIELDS},
            'current_availability':'not_inferred','replacement_suitability':'not_assessed'})
    return result


def load(con, season, team_id, cutoff):
    games = rows(con,
        "SELECT g.game_id,max(g.game_date) AS game_date,count(*) AS matching_rows FROM nba.main.team_game_logs g JOIN nba.main.schedule s ON g.season=s.season AND g.game_id=s.game_id AND g.game_date=s.game_date WHERE g.season=? AND g.team_id=? AND g.game_date<? AND g.game_id LIKE '002%' AND g.team_id IN (s.home_team_id,s.away_team_id) AND lower(trim(s.status)) IN ('3','final','completed','complete','post') GROUP BY g.game_id ORDER BY game_date DESC,g.game_id LIMIT 10",
        [season,team_id,cutoff])
    if not games or any(g['matching_rows']!=1 for g in games):
        raise ValueError('Missing or ambiguous completed team-game sample')
    ids = [g['game_id'] for g in games]
    marks = ','.join('?' for _ in ids)
    records = rows(con,'SELECT game_id,player_id,team_id,game_date,pts,fga,fg3a,ast,reb FROM nba.main.player_game_logs WHERE season=? AND team_id=? AND game_id IN ('+marks+') ORDER BY game_date,game_id,player_id LIMIT 1001',[season,team_id]+ids)
    dates = {g['game_id']:g['game_date'] for g in games}
    if any(r['game_date']!=dates[r['game_id']] for r in records):
        raise ValueError('Player/team game date mismatch')
    profiles = summarize(records,ids,team_id,cutoff)
    body = json.dumps(records,sort_keys=True,default=str,separators=(',',':')).encode()
    return {'status':'observed_contributions_only','team_game_count':len(games),'games':games,
            'cutoff_date_exclusive':cutoff.isoformat(),'profiles':profiles,'rows_sha256':hashlib.sha256(body).hexdigest()}


def enrich(report, now, connector=None):
    import copy
    result = copy.deepcopy(report)
    result['role_profiles'] = {'status':'blocked','source':SOURCE,'read_only':True,
        'source_read_attempted':False,'role_assessment_complete':False,
        'limitations':[
            'Last ten source-known completed regular-season team games; no independent completion or publication verification.',
            'Means use returned player records, not assumed appearances. Missing rows are not zero-filled or labelled injured.',
            'Attempts, assists and rebounds describe recorded contributions, not causal impact or complete basketball roles.',
            'Recent teammates are not verified current roster members, available replacements or lineup-compatible substitutes.',
            'No minutes conversion, scenario weights, point adjustments or probability changes.']}
    if report.get('personnel_evidence',{}).get('status')!='bound_snapshot_only':
        result['role_profiles']['error'] = 'Bound personnel snapshot required'
        return result
    if len(report['fixtures'])>30:
        raise ValueError('Fixture resource limit exceeded')
    con = None
    failures = []
    count = 0
    cache = {}
    try:
        for g in result['fixtures']:
            if g['status']!='descriptive_team_analysis_only' or stamp(g['start_time_utc'])<=now:
                continue
            tip = stamp(g['start_time_utc']).astimezone(ZoneInfo('America/New_York'))
            cutoff = min(now.astimezone(dt.timezone.utc).date(),tip.date(),
                         stamp(report['personnel_evidence']['published_at_utc']).astimezone(ZoneInfo('America/New_York')).date())
            season = tip.year+int(tip.month>=10)
            for side in ('home','away'):
                tid = g['teams'][side]['team_id']
                key = (season,tid,cutoff)
                try:
                    if con is None:
                        if connector is None:
                            import duckdb
                            connector = duckdb.connect
                        con = connector()
                        result['role_profiles']['source_read_attempted'] = True
                        con.execute("ATTACH '"+SOURCE+"' AS nba (READ_ONLY)")
                    if key not in cache:
                        cache[key] = load(con,season,tid,cutoff)
                    profile = copy.deepcopy(cache[key])
                    g.setdefault('contribution_profiles',{})[side] = profile
                    count += 1
                    by_id = {p['player_id']:p for p in profile['profiles']}
                    for p in g.get('personnel',{}).get(side,{}).get('records',[]):
                        pid = p.get('player_id')
                        p['historical_contributions'] = by_id.get(pid) if p.get('database_match_verified') is True else None
                        p['contribution_status'] = 'matched_recent_records' if p['historical_contributions'] else 'identity_unresolved' if not p.get('database_match_verified') else 'no_records_in_selected_window'
                except Exception as exc:
                    error = str(exc)[:400]
                    g.setdefault('contribution_profiles',{})[side] = {'status':'unavailable','error':error}
                    failures.append({'game_id':g['game_id'],'side':side,'error':error})
    finally:
        if con is not None:
            con.close()
    result['role_profiles'].update(status='partial_failure' if failures else 'observed_contributions_only' if count else 'no_pregame_teams',
                                  team_profiles=count,errors=failures)
    return result


def main():
    import analysis_personnel
    analysis_personnel.main()
    folder = Path('team-analysis-results')
    report = json.loads((folder/'result.json').read_text())
    try:
        report = enrich(report,dt.datetime.now(dt.timezone.utc))
    except Exception as exc:
        report['role_profiles'] = {'status':'failed','error':str(exc)[:400],'role_assessment_complete':False}
    (folder/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False,default=str)+'\n')
    summary = {'schema':'team-analysis-summary-v1','generated_at_utc':report.get('generated_at_utc'),
        'source_commit_sha':report.get('source_commit_sha'),'team_execution_ok':report.get('execution_ok'),
        'personnel_status':report.get('personnel_evidence',{}).get('status'),
        'role_profiles':report['role_profiles'],'analysis_complete':False,'betting_release':False,
        'fixtures':[{'game_id':g['game_id'],'status':g['status'],
                     'profiles':{side:{k:p.get(k) for k in ('status','team_game_count','error')} for side,p in g.get('contribution_profiles',{}).items()}}
                    for g in report['fixtures']]}
    (folder/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    lines = ['', '## Historische Spielerbeitraege',json.dumps(report['role_profiles'],ensure_ascii=True)]
    for g in report['fixtures']:
        for side,p in g.get('contribution_profiles',{}).items():
            lines += ['### '+g['game_id']+' '+side, 'Status: '+p['status']]
            for r in p.get('profiles',[]):
                values = ', '.join(k+'='+format(v,'.2f') for k,v in r['mean_per_record'].items())
                lines.append(r['player_id']+': '+str(r['observed_records'])+' Quellzeilen; '+values)
    with (folder/'result.md').open('a') as f:
        f.write('\n\n'.join(lines)+'\n')
    return 0 if report.get('execution_ok') is True and report['role_profiles']['status'] in ('observed_contributions_only','no_pregame_teams') else 1


if __name__ == '__main__':
    raise SystemExit(main())
