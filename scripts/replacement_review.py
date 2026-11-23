"""Evidence gates for replacement review; never infer a healthy full roster."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from team_analysis import stamp
from player_role_profiles import SOURCE,rows

DIMENSIONS = ('fga','fg3a','ast','reb')


def assess(profiles, personnel, roster, team_id, cutoff, team_game_count=None):
    if len(profiles)>200 or len(roster)>1000:
        raise ValueError('Replacement review resource limit exceeded')
    if team_game_count is not None and (type(team_game_count) is not int or not 1<=team_game_count<=10):
        raise ValueError('Invalid team game count')
    by_profile = {}
    for p in profiles:
        pid = p['player_id']
        if not isinstance(pid,str) or not pid.strip() or pid in by_profile:
            raise ValueError('Invalid or duplicate profile ID')
        if type(p['observed_records']) is not int or p['observed_records']<1:
            raise ValueError('Invalid observed record count')
        if team_game_count is not None and p['observed_records']>team_game_count:
            raise ValueError('Observed records exceed selected team games')
        by_profile[pid] = p
    totals = {pid:p['mean_per_record']['fga']*p['observed_records'] for pid,p in by_profile.items()}
    team_total = sum(totals.values())
    ranks = {value:i+1 for i,value in enumerate(sorted(set(totals.values()),reverse=True))}
    statuses = {}
    if personnel.get('status')=='reported_statuses_only':
        for p in personnel.get('records',[]):
            if p.get('database_match_verified') is not True:
                continue
            pid = p.get('player_id')
            if not isinstance(pid,str) or not pid.strip() or pid in statuses:
                raise ValueError('Invalid or duplicate personnel ID')
            if p['reported_status'] not in ('Out','Doubtful','Questionable','Probable','Available'):
                raise ValueError('Unsupported personnel status')
            statuses[pid] = p
    references = {}
    for r in roster:
        if not isinstance(r['as_of_date'],dt.date) or isinstance(r['as_of_date'],dt.datetime) or r['as_of_date']>=cutoff:
            raise ValueError('Nonhistorical roster reference')
        references.setdefault(r['player_id'],[]).append(r)
    output = []
    for pid in sorted(set(by_profile)|set(statuses)):
        candidates = references.get(pid,[])
        if candidates:
            latest = max(r['as_of_date'] for r in candidates)
            candidates = [r for r in candidates if r['as_of_date']==latest]
        relation = 'missing' if not candidates else 'ambiguous' if len(candidates)!=1 else 'matching_prior_team' if candidates[0]['team_id']==team_id else 'different_prior_team'
        p = statuses.get(pid)
        status = p['reported_status'] if p else None
        availability = 'reported_out' if status=='Out' else 'conditional' if status in ('Doubtful','Questionable','Probable') else 'explicit_available' if status=='Available' else 'not_verified'
        profile = by_profile.get(pid)
        known = profile is not None and team_game_count is not None
        appeared_all = (profile['observed_records']==team_game_count) if known else None
        gates = relation=='matching_prior_team' and availability=='explicit_available' and profile is not None
        review = gates and appeared_all is False
        regular = gates and appeared_all is True
        output.append({'player_id':pid,'source_name':p['source_name'] if p else None,
            'reported_status':status,'availability_evidence':availability,'prior_roster_relation':relation,
            'roster_as_of_date':candidates[0]['as_of_date'].isoformat() if len(candidates)==1 else None,
            'prior_reference_age_days':(cutoff-candidates[0]['as_of_date']).days if len(candidates)==1 else None,
            'current_team_membership_verified':False,
            'participation_share':profile['observed_records']/team_game_count if known else None,
            'appeared_in_all_selected_games':appeared_all,
            'recorded_fga_share':totals[pid]/team_total if profile is not None and team_total>0 else None,
            'recorded_fga_rank':ranks[totals[pid]] if profile is not None else None,
            'candidate_for_further_role_review':review,
            'available_full_participation':regular,
            'replacement_confirmed':False,
            'recent_profile':profile})
    dimensions = {}
    for metric in DIMENSIONS:
        def participants(predicate):
            return [{'player_id':p['player_id'],'mean_per_record':p['recent_profile']['mean_per_record'][metric],
                     'observed_records':p['recent_profile']['observed_records']} for p in output
                    if predicate(p) and p['recent_profile'] is not None and p['recent_profile']['mean_per_record'][metric]>0]
        dimensions[metric] = {
            'reported_out_observed_contributors':participants(lambda p:p['availability_evidence']=='reported_out'),
            'conditional_observed_contributors':participants(lambda p:p['availability_evidence']=='conditional'),
            'review_candidates_with_observed_contribution':participants(lambda p:p['candidate_for_further_role_review']),
            'available_full_participants_with_observed_contribution':participants(lambda p:p['available_full_participation']),
            'capacity_or_compensation_proven':False}
    return {'status':'evidence_screen_only','cutoff_date_exclusive':cutoff.isoformat(),'team_game_count':team_game_count,'players':output,
        'candidate_count':sum(p['candidate_for_further_role_review'] for p in output),
        'available_full_participation_count':sum(p['available_full_participation'] for p in output),
        'contribution_dimensions':dimensions,'role_assessment_complete':False,'replacement_assignment':None,
        'note':'Candidates need explicit Available status, a matching prior dated roster reference, a recent profile and absence from at least one selected team game. Players present in every selected game are listed separately as regular participants, not added options. Prior roster references are not current-roster proof. Missing status is unknown. No contributions are added as an expected team loss.'}


def summarize_review(review):
    keys = ('player_id','source_name','participation_share','recorded_fga_share','recorded_fga_rank')
    def pick(player):
        return {k:player.get(k) for k in keys}
    return {'status':review.get('status'),'candidate_count':review.get('candidate_count'),
            'available_full_participation_count':review.get('available_full_participation_count'),
            'candidates':[pick(p) for p in review.get('players',[]) if p['candidate_for_further_role_review']],
            'available_full_participants':[pick(p) for p in review.get('players',[]) if p['available_full_participation']],
            'error':review.get('error')}


def load_roster(con, season, ids, cutoff):
    ids = sorted(set(ids))
    if len(ids)>200:
        raise ValueError('Roster player request limit exceeded')
    if not ids:
        return []
    marks = ','.join('?' for _ in ids)
    sql = ('WITH latest AS (SELECT player_id,max(as_of_date) AS as_of_date FROM nba.main.rosters_daily WHERE season=? AND as_of_date<? AND player_id IN ('+marks+') GROUP BY player_id) '
           'SELECT r.player_id,r.team_id,r.as_of_date FROM nba.main.rosters_daily r JOIN latest l ON r.player_id=l.player_id AND r.as_of_date=l.as_of_date WHERE r.season=? ORDER BY r.player_id,r.team_id LIMIT 1001')
    result = rows(con,sql,[season,cutoff]+ids+[season])
    if len(result)>1000:
        raise ValueError('Roster source-row limit exceeded')
    return result


def enrich(report, now, connector=None):
    result = copy.deepcopy(report)
    result['replacement_review'] = {'status':'blocked','source':SOURCE,'read_only':True,'source_read_attempted':False,
        'role_assessment_complete':False,'historical_publication_verified':False,'team_reviews':0,'errors':[]}
    if report.get('personnel_evidence',{}).get('status')!='bound_snapshot_only':
        return result
    con = None
    cache = {}
    try:
        for g in result['fixtures']:
            if g['status']!='descriptive_team_analysis_only' or stamp(g['start_time_utc'])<=now:
                continue
            tip = stamp(g['start_time_utc']).astimezone(ZoneInfo('America/New_York'))
            cutoff = min(now.astimezone(dt.timezone.utc).date(),tip.date(),
                stamp(report['personnel_evidence']['published_at_utc']).astimezone(ZoneInfo('America/New_York')).date())
            season = tip.year+int(tip.month>=10)
            g['replacement_review'] = {}
            for side in ('home','away'):
                try:
                    profile = g.get('contribution_profiles',{}).get(side,{})
                    if profile.get('status')!='observed_contributions_only':
                        raise ValueError('Recent contribution profiles unavailable')
                    people = g.get('personnel',{}).get(side,{})
                    ids = [p['player_id'] for p in profile['profiles']]
                    ids += [p['player_id'] for p in people.get('records',[]) if p.get('database_match_verified') is True]
                    key = (season,cutoff,tuple(sorted(set(ids))))
                    if con is None:
                        if connector is None:
                            import duckdb
                            connector = duckdb.connect
                        con = connector()
                        result['replacement_review']['source_read_attempted'] = True
                        con.execute("ATTACH '"+SOURCE+"' AS nba (READ_ONLY)")
                    if key not in cache:
                        cache[key] = load_roster(con,season,ids,cutoff)
                    roster = cache[key]
                    review = assess(profile['profiles'],people,roster,g['teams'][side]['team_id'],cutoff,profile.get('team_game_count'))
                    review['roster_rows_sha256'] = hashlib.sha256(json.dumps(roster,sort_keys=True,default=str).encode()).hexdigest()
                    g['replacement_review'][side] = review
                    result['replacement_review']['team_reviews'] += 1
                except Exception as exc:
                    error = str(exc)[:400]
                    g['replacement_review'][side] = {'status':'unavailable','error':error}
                    result['replacement_review']['errors'].append({'game_id':g['game_id'],'side':side,'error':error})
    finally:
        if con is not None:
            con.close()
    state = result['replacement_review']
    state['status'] = 'partial_failure' if state['errors'] else 'evidence_screen_only' if state['team_reviews'] else 'no_pregame_teams'
    return result


def main():
    import player_role_profiles
    player_role_profiles.main()
    folder = Path('team-analysis-results')
    report = json.loads((folder/'result.json').read_text())
    try:
        report = enrich(report,dt.datetime.now(dt.timezone.utc))
    except Exception as exc:
        report['replacement_review'] = {'status':'failed','error':str(exc)[:400],'role_assessment_complete':False}
    (folder/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False,default=str)+'\n')
    summary = json.loads((folder/'summary.json').read_text())
    summary['replacement_review'] = report['replacement_review']
    for item in summary['fixtures']:
        game = next(g for g in report['fixtures'] if g['game_id']==item['game_id'])
        item['replacement_review'] = {side:summarize_review(r) for side,r in game.get('replacement_review',{}).items()}
    (folder/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    lines = ['','## Ersatzpruefung: belegte Voraussetzungen, keine fertige Rollenbewertung']
    for g in report['fixtures']:
        for side,r in g.get('replacement_review',{}).items():
            lines += ['### '+g['game_id']+' '+side,r['status'],
                '| Spieler-ID | Name laut Meldung | Gemeldeter Status | Kaderreferenz | Teilnahmeanteil | Anteil erfasster Wurfversuche | Gruppe |',
                '|---|---|---|---|---|---|---|']
            for p in r.get('players',[]):
                group = 'zusaetzliche Option (Pruefkandidat)' if p['candidate_for_further_role_review'] else 'regulaer beteiligt, verfuegbar' if p['available_full_participation'] else 'nicht eingeordnet'
                share = '-' if p['participation_share'] is None else format(p['participation_share'],'.2f')
                volume = '-' if p['recorded_fga_share'] is None else format(p['recorded_fga_share'],'.3f')
                lines.append('| '+' | '.join(str(v) for v in (p['player_id'],p['source_name'] or '-',p['reported_status'] or 'unbekannt',p['prior_roster_relation'],share,volume,group))+' |')
            if r.get('error'):lines.append(r['error'])
    with (folder/'result.md').open('a') as f:
        f.write('\n\n'.join(lines)+'\n')
    return 0 if report.get('execution_ok') is True and report['replacement_review']['status'] in ('evidence_screen_only','no_pregame_teams') and report.get('role_profiles',{}).get('status') in ('observed_contributions_only','no_pregame_teams') else 1


if __name__ == '__main__':
    raise SystemExit(main())
