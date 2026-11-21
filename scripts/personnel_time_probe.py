"""Bounded chronology/roster probe; no historical publication or model approval."""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from player_source_probe import SOURCE, rows

NEEDED = {'injury_report':set('season report_time game_id game_date team_id player_id status'.split()),
          'schedule':set('season game_id start_time home_team_id away_team_id'.split()),
          'rosters_daily':set('season as_of_date team_id player_id'.split())}


def aware(value):
    return isinstance(value,dt.datetime) and value.tzinfo is not None and value.utcoffset() is not None


def inspect(con, now, limit=10):
    if not aware(now) or type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Aware audit time and sample limit 1..10 required')
    now=now.astimezone(dt.timezone.utc);season=now.year+int(now.month>=10)
    columns=rows(con,"SELECT table_name,column_name FROM duckdb_columns() WHERE database_name='nba' AND schema_name='main' AND internal=false")
    for table,needed in NEEDED.items():
        found={r['column_name'] for r in columns if r['table_name']==table}
        if not needed<=found:raise ValueError('Missing columns in '+table+': '+','.join(sorted(needed-found)))
    profile=rows(con,"SELECT count(*) AS regular_season_report_rows,min(report_time) AS first_report_time,max(report_time) AS last_report_time,count(*) FILTER (WHERE report_time IS NULL) AS missing_report_times,count(*) FILTER (WHERE report_time>?) AS future_report_times FROM nba.main.injury_report WHERE season=? AND game_id LIKE '002%'",[now,season])[0]
    sample=rows(con,"SELECT season,report_time,game_id,game_date,team_id,player_id,status FROM nba.main.injury_report WHERE season=? AND game_id LIKE '002%' AND report_time<=? ORDER BY report_time DESC,game_id,team_id,player_id LIMIT ?",[season,now,limit])
    games=sorted({r['game_id'] for r in sample});schedule={}
    if games:
        marks=','.join('?' for _ in games)
        matches=rows(con,'SELECT game_id,count(*) AS schedule_rows,min(start_time) AS scheduled_tip,min(home_team_id) AS home_team_id,min(away_team_id) AS away_team_id FROM nba.main.schedule WHERE season=? AND game_id IN ('+marks+') GROUP BY game_id',[season]+games)
        schedule={r['game_id']:r for r in matches}
    cache={};seen=set()
    for r in sample:
        reasons=[];s=schedule.get(r['game_id']);r['roster_candidates']=[]
        r['roster_relation']='not_checked';r['scheduled_tip']=None
        for field in ('game_id','team_id','player_id','status'):
            if r[field] is None or not str(r[field]).strip():reasons.append('missing_'+field)
        key=(r['season'],r['report_time'],r['game_id'],r['team_id'],r['player_id'])
        if key in seen:reasons.append('duplicate_candidate_key_in_sample')
        seen.add(key)
        if s is None:r['timing_relation']='schedule_missing'
        elif s['schedule_rows']!=1:r['timing_relation']='schedule_ambiguous'
        elif not aware(s['scheduled_tip']) or not aware(r['report_time']):r['timing_relation']='time_unusable'
        else:
            tip=s['scheduled_tip'];r['scheduled_tip']=tip
            r['timing_relation']='before_scheduled_tip' if r['report_time']<tip else 'at_or_after_scheduled_tip'
            if not s['home_team_id'] or not s['away_team_id'] or s['home_team_id']==s['away_team_id']:
                reasons.append('invalid_scheduled_teams')
            if r['team_id'] not in (s['home_team_id'],s['away_team_id']):reasons.append('team_not_in_schedule')
            day=tip.astimezone(ZoneInfo('America/New_York')).date()
            if r['game_date']!=day:reasons.append('game_date_differs_from_scheduled_et_date')
            if r['player_id'] is not None and str(r['player_id']).strip():
                ck=(season,r['player_id'],day)
                if ck not in cache:
                    cache[ck]=rows(con,'SELECT as_of_date,team_id,count(*) AS rows_at_date FROM nba.main.rosters_daily WHERE season=? AND player_id=? AND as_of_date=(SELECT max(as_of_date) FROM nba.main.rosters_daily WHERE season=? AND player_id=? AND as_of_date<?) GROUP BY as_of_date,team_id ORDER BY team_id LIMIT 3',[season,r['player_id'],season,r['player_id'],day])
                roster=cache[ck];r['roster_candidates']=roster
                if not roster:r['roster_relation']='prior_date_missing'
                elif len(roster)!=1 or roster[0]['rows_at_date']!=1:r['roster_relation']='prior_date_ambiguous'
                elif roster[0]['team_id']==r['team_id']:r['roster_relation']='matching_prior_date_candidate'
                else:r['roster_relation']='different_team_at_prior_date'
        r['issues']=reasons
    return {'season_end_year':season,'sample_limit':limit,'sample_rows_read':len(sample),'profile':profile,'sample':sample,
        'before_scheduled_tip_rows':sum(r['timing_relation']=='before_scheduled_tip' for r in sample),
        'at_or_after_scheduled_tip_rows':sum(r['timing_relation']=='at_or_after_scheduled_tip' for r in sample),
        'matching_prior_date_roster_rows':sum(r['roster_relation']=='matching_prior_date_candidate' for r in sample),
        'historical_publication_provenance_verified':False,'model_input_approved':False,
        'limitations':['Current season and at most ten report records; no full-history quality or coverage claim.',
            'report_time before scheduled start is a timestamp relation, not proof of historical publication or absence of backfill.',
            'Roster dates are strictly earlier than the scheduled game date in America/New_York. Same-day snapshots are not assigned an invented intraday time.',
            'The latest earlier dated roster is a candidate, not proof that no intervening trade or roster change occurred.',
            'Stored scheduled tip-off is not independently verified actual tip-off. No probabilities, model training or recommendations.']}


def probe(now, connector=None):
    report={'schema':'personnel-time-probe-v1','checked_at_utc':now.isoformat(),'source':SOURCE,'read_only':True,
            'execution_ok':False,'production_model_changed':False,'betting_release':False}
    con=None
    try:
        if connector is None:
            import duckdb
            connector=duckdb.connect
        con=connector();con.execute("ATTACH '"+SOURCE+"' AS nba (READ_ONLY)")
        report.update(inspect(con,now));report['execution_ok']=True
    except Exception as exc:report['error']=(type(exc).__name__+': '+str(exc))[:600]
    finally:
        if con is not None:con.close()
    return report


def write_report(report, root=Path('diagnostics')):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    (root/'personnel_time_probe.json').write_text(json.dumps(report,default=str,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# Personal-Zeitbezug und Kaderstichprobe','', 'Pruefzeit UTC: '+report['checked_at_utc'],
        'Quelle: '+report['source'],'Ausfuehrung erfolgreich: '+str(report['execution_ok']),
        'Keine historische Veroeffentlichungs- oder Modellfreigabe.','']
    if report.get('error'):lines+=['Fehler: '+report['error'].replace('\n',' '),'']
    if report['execution_ok']:
        lines+=['Gelesene Berichtszeilen: '+str(report['sample_rows_read']),
            'Zeitstempel vor geplantem Spielbeginn: '+str(report['before_scheduled_tip_rows']),
            'Zeitstempel ab geplantem Spielbeginn: '+str(report['at_or_after_scheduled_tip_rows']),
            'Passende fruehere Kaderdatums-Kandidaten: '+str(report['matching_prior_date_roster_rows']),
            'Quellenumfang: '+str(report['profile']),'','[Einzelzeilen und genaue Befunde](personnel_time_probe.json)','']+report['limitations']
    (root/'personnel_time_probe.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    report=probe(dt.datetime.now(dt.timezone.utc));write_report(report)
    raise SystemExit(0 if report['execution_ok'] and report['sample_rows_read'] else 1)


if __name__=='__main__':
    main()
