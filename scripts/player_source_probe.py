"""Read-only player-log sample probe; no model or personnel-effect validation."""
import datetime as dt
import json
import math
from pathlib import Path

SOURCE = 'https://basketball-data.billmill.org/nba/nba.duckdb'
NEEDED = {'player_game_logs':{'season','game_id','player_id','team_id','opp_team_id','game_date','min'},
          'players':{'player_id','name','first_season','last_season'}}


def rows(con, sql, params=None):
    cursor = con.execute(sql, [] if params is None else params)
    return [dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()]


def inspect(con, now, limit=10):
    if now.tzinfo is None or type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('Aware time and sample limit 1..20 required')
    now = now.astimezone(dt.timezone.utc)
    season = now.year + int(now.month >= 10)
    columns = rows(con, "SELECT table_name, column_name FROM duckdb_columns() WHERE database_name='nba' AND schema_name='main' AND internal=false")
    for table, required in NEEDED.items():
        found = {r['column_name'] for r in columns if r['table_name']==table}
        if not required <= found:
            raise ValueError('Missing required columns in '+table+': '+','.join(sorted(required-found)))
    profile = rows(con, "SELECT count(*) AS season_rows, min(game_date) AS first_game_date, max(game_date) AS latest_game_date, count(*) FILTER (WHERE game_date IS NULL) AS missing_date_rows, count(*) FILTER (WHERE game_date < ?) AS eligible_rows FROM nba.main.player_game_logs WHERE season=?", [now.date(),season])[0]
    sample = rows(con, "SELECT season,game_id,player_id,team_id,opp_team_id,game_date,min FROM nba.main.player_game_logs WHERE season=? AND game_date < ? ORDER BY game_date DESC,game_id,player_id,team_id LIMIT ?", [season,now.date(),limit])
    issues, seen = [], set()
    ids = sorted({str(r['player_id']) for r in sample if r['player_id'] is not None and str(r['player_id']).strip()})
    identities = []
    if ids:
        marks = ','.join('?' for _ in ids)
        identities = rows(con, 'SELECT player_id,count(*) AS identity_rows,min(name) AS example_name,min(first_season) AS first_season,max(last_season) AS last_season FROM nba.main.players WHERE player_id IN ('+marks+') GROUP BY player_id ORDER BY player_id', ids)
    identity_map = {str(r['player_id']):r for r in identities}
    for i,r in enumerate(sample,1):
        reasons = []
        for field in ('game_id','player_id','team_id','opp_team_id'):
            if r[field] is None or not str(r[field]).strip():
                reasons.append('missing_'+field)
        key = (r['season'],r['game_id'],r['player_id'])
        if key in seen:reasons.append('duplicate_candidate_key_in_sample')
        seen.add(key)
        if r['team_id'] == r['opp_team_id']:reasons.append('same_team_and_opponent')
        value = r['min']
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            reasons.append('invalid_minutes_field')
        identity = identity_map.get(str(r['player_id']))
        if identity is None:reasons.append('player_id_not_found')
        elif identity['identity_rows'] != 1:reasons.append('ambiguous_player_id')
        elif not isinstance(identity['example_name'],str) or not identity['example_name'].strip():
            reasons.append('missing_player_name')
        if reasons:issues.append({'sample_row':i,'reasons':reasons})
    for r in sample:
        if isinstance(r['min'],float) and not math.isfinite(r['min']):r['min']=repr(r['min'])
    for r in identities:
        if r['identity_rows'] != 1:r['example_name']=None
    return {'season_end_year':season,'cutoff_utc_date_exclusive':now.date().isoformat(),
        'sample_limit':limit,'profile_scope':'Current-season player logs; sample excludes current UTC date and later.',
        'profile':profile,'sample_rows_read':len(sample),'sample':sample,'identities':identities,
        'sample_issues':issues,'sample_basic_checks_ok':bool(sample) and not issues,
        'sample_truncated':profile['eligible_rows']>len(sample),
        'historical_pregame_personnel_verified':False,'minutes_semantics_verified':False,
        'limitations':['Sample-only duplicate and identity checks are not a full-table quality audit.',
            'The min field is inspected, not yet approved as a model feature; zero is not inferred to mean injured or absent.',
            'Date and season fields do not prove historical publication time or then-current roster membership.',
            'No model training or automatic recommendation. Nonfinite sample numbers are retained as text.']}


def probe(now, connector=None):
    report = {'schema':'player-source-probe-v1','checked_at_utc':now.isoformat(),'source':SOURCE,
        'execution_ok':False,'read_only':True,'player_training_rows_imported':0,
        'production_model_changed':False,'betting_release':False}
    con = None
    try:
        if connector is None:
            import duckdb
            connector = duckdb.connect
        con = connector()
        con.execute("ATTACH '"+SOURCE+"' AS nba (READ_ONLY)")
        report.update(inspect(con,now))
        report['execution_ok']=True
    except Exception as exc:
        report['error']=(type(exc).__name__+': '+str(exc))[:600]
    finally:
        if con is not None:con.close()
    return report


def write_report(report, root=Path('diagnostics')):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    (root/'player_source_probe.json').write_text(json.dumps(report,default=str,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    lines=['# Spielerquellen-Stichprobe','', 'Pruefzeit UTC: '+report['checked_at_utc'],
        'Quelle: '+report['source'],'Ausfuehrung erfolgreich: '+str(report['execution_ok']),
        'Keine Modell- oder Wettfreigabe. Keine Trainingsdaten importiert.','']
    if report.get('error'):lines+=['Fehler: '+report['error'].replace('\n',' '),'']
    if report['execution_ok']:
        lines+=['Saison-Endjahr: '+str(report['season_end_year']),
            'Datumsgrenze exklusiv (UTC): '+report['cutoff_utc_date_exclusive'],
            'Saisonumfang laut Quelle: '+str(report['profile']),
            'Gelesene Stichprobenzeilen: '+str(report['sample_rows_read']),
            'Grundpruefungen dieser Stichprobe bestanden: '+str(report['sample_basic_checks_ok']),
            'Stichprobenbefunde: '+json.dumps(report['sample_issues'],ensure_ascii=True),'',
            '[Konkrete Zeilen und Spielerzuordnungen](player_source_probe.json)','']
        lines+=report['limitations']
    (root/'player_source_probe.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    report=probe(dt.datetime.now(dt.timezone.utc))
    write_report(report)
    raise SystemExit(0 if report['execution_ok'] and report['sample_basic_checks_ok'] else 1)


if __name__=='__main__':
    main()
