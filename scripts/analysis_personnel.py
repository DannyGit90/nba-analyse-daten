"""Bind official personnel evidence to team analysis; no impact weights."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from personnel_records import build as replay
from team_analysis import stamp


def digest(body):
    return hashlib.sha256(body).hexdigest()


def bind(report, raw_bytes, player_bytes, identity_bytes, now):
    if any(not isinstance(b,bytes) or len(b)>2000000 for b in (raw_bytes,player_bytes,identity_bytes)):
        raise ValueError('Personnel byte limit exceeded')
    raw, players, identities = [json.loads(b) for b in (raw_bytes,player_bytes,identity_bytes)]
    if players.get('execution_ok') is not True or identities.get('execution_ok') is not True:
        raise ValueError('Personnel processing did not succeed')
    if players.get('betting_release') is not False or identities.get('betting_release') is not False:
        raise ValueError('Unexpected personnel release')
    if players.get('source_snapshot_sha256') != digest(raw_bytes) or identities.get('raw_snapshot_sha256') != digest(raw_bytes):
        raise ValueError('Raw personnel snapshot hash mismatch')
    if identities.get('player_snapshot_sha256') != digest(player_bytes):
        raise ValueError('Player snapshot hash mismatch')
    expected = replay(raw,now)
    if any(players.get(k)!=v for k,v in expected.items() if k!='generated_at_utc'):
        raise ValueError('Player parser replay mismatch')
    published = stamp(players['source_published_at_utc'])
    if not published <= stamp(players['source_checked_at_utc']) <= stamp(players['generated_at_utc']) <= stamp(identities['generated_at_utc']) <= now:
        raise ValueError('Personnel timestamps inconsistent')
    if now-published > dt.timedelta(hours=8):
        raise ValueError('Stale personnel source')
    if identities.get('source_published_at_utc') != players['source_published_at_utc']:
        raise ValueError('Identity publication mismatch')
    if len(players['sections'])>100 or len(identities['records'])>1000:
        raise ValueError('Personnel resource limit exceeded')
    mapping = {}
    for r in identities['records']:
        key = (r['section_index'],r['source_record_index'])
        if key in mapping:
            raise ValueError('Duplicate identity record key')
        mapping[key] = r
    output = copy.deepcopy(report)
    output['personnel_evidence'] = {'status':'bound_snapshot_only','published_at_utc':players['source_published_at_utc'],
        'source':players['source'],'raw_sha256':digest(raw_bytes),'players_sha256':digest(player_bytes),
        'identities_sha256':digest(identity_bytes),'latest_available_verified':False,
        'role_assessment_complete':False,'historical_publication_verified':False}
    for game in output['fixtures']:
        if game['status']!='descriptive_team_analysis_only':
            continue
        tip = stamp(game['start_time_utc'])
        if tip <= now:
            game['personnel'] = {'status':'started_not_assessed'}
            continue
        if published >= tip:
            game['personnel'] = {'status':'source_not_pregame'}
            continue
        date = tip.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        game['personnel'] = {}
        for side in ('home','away'):
            team = game['teams'][side]
            matches = [(i,s) for i,s in enumerate(players['sections']) if
                (s['game_date_et'],s['home'],s['away'],s['team']) == (date,game['home'],game['away'],team['team'])]
            entry = {'status':'missing_section','records':[],'role_assessment_complete':False,
                     'absence_of_entry_means_healthy':False}
            game['personnel'][side] = entry
            if len(matches)!=1:
                if matches:entry['status'] = 'ambiguous_sections'
                continue
            si,section = matches[0]
            if section['status']=='not_submitted':
                entry['status'] = 'not_submitted'
                continue
            if section.get('parsing_complete') is not True or section.get('errors'):
                entry['status'] = 'unresolved_section'
                continue
            entry['status'] = 'reported_statuses_only'
            used = set()
            for pi,p in enumerate(section['players']):
                r = mapping.get((si,pi),{})
                same = all(r.get(k)==v for k,v in {'game_date_et':date,'home':game['home'],'away':game['away'],
                    'team':team['team'],'name_candidate':p['name_candidate'],'status':p['status']}.items())
                match = r.get('match',{})
                pid = match.get('player_id')
                verified = same and match.get('match_verified') is True and r.get('expected_team_id')==team['team_id'] and isinstance(pid,str) and bool(pid.strip())
                if verified and pid in used:
                    raise ValueError('Duplicate player ID in section')
                if verified:used.add(pid)
                status = p['status']
                scenarios = ['reported_unavailable'] if status=='Out' else ['reported_available_no_minutes_guarantee'] if status=='Available' else ['plays','does_not_play']
                entry['records'].append({'source_name':p['name_candidate'],'reported_status':status,'reason':p['reason_text'],
                    'player_id':pid if verified else None,'database_match_verified':bool(verified),
                    'source_section_index':si,'source_record_index':pi,'availability_scenarios':scenarios,
                    'scenario_weights':None,'replacement_roles':None,'impact_quantified':False})
            game['findings'].append(team['team']+': gemeldete Personalstatus verknuepft; Rollen, Ersatz und Wirkung noch nicht bewertet.')
    return output


def main():
    import team_analysis
    team_analysis.main()
    folder = Path('team-analysis-results')
    report = json.loads((folder/'result.json').read_text())
    now = dt.datetime.now(dt.timezone.utc)
    try:
        if report.get('execution_ok') is not True:
            raise ValueError('Team analysis incomplete or failed')
        root = Path('reports/injury')
        report = bind(report,(root/'latest.json').read_bytes(),(root/'players_latest.json').read_bytes(),
                      (root/'identities_latest.json').read_bytes(),now)
    except Exception as exc:
        report['personnel_evidence'] = {'status':'unavailable_or_invalid','error':str(exc)[:400],
                                        'role_assessment_complete':False}
    (folder/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    lines = ['','## Verknuepfter Personalstand','',json.dumps(report['personnel_evidence'],ensure_ascii=True)]
    for g in report['fixtures']:
        if 'personnel' in g:
            lines += ['', '### '+g['game_id'],json.dumps(g['personnel'],ensure_ascii=True,indent=2)]
    with (folder/'result.md').open('a') as f:
        f.write('\n'.join(lines)+'\n')
    return 0 if report.get('execution_ok') is True and report['personnel_evidence']['status']=='bound_snapshot_only' else 1


if __name__ == '__main__':
    raise SystemExit(main())
