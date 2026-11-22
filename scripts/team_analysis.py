"""Descriptive team-analysis stage, not a probability or recommendation engine."""
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

METRICS = ('off_rating','def_rating','pace')


def stamp(value):
    result = dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Aware timestamp required')
    return result


def analyze(page, forecast, generation, protocol, now):
    if page.get('generated_at_utc') != generation or page.get('protocol') != protocol:
        raise ValueError('Context snapshot mismatch')
    source_time = stamp(generation)
    if not source_time <= now or now-source_time > dt.timedelta(hours=8):
        raise ValueError('Future or stale context')
    f = page['fixture']
    for field in ('game_id','home','away','start_time_utc'):
        if f[field] != forecast[field]:
            raise ValueError('Fixture identity mismatch: '+field)
    tip = stamp(f['start_time_utc'])
    if tip <= now:
        return {'game_id':f['game_id'],'status':'started_not_assessed','betting_release':False}
    if tip > now+dt.timedelta(hours=24):
        return {'game_id':f['game_id'],'status':'outside_window_not_assessed','betting_release':False}
    teams = {}
    for side in ('home','away'):
        c = f[side+'_context']
        if c['team_id'] != forecast[side+'_team_id']:
            raise ValueError('Team identity mismatch')
        n, last_n = c['season_games'],c['last10_games']
        if type(n) is not int or type(last_n) is not int or not 1 <= last_n <= min(10,n):
            raise ValueError('Invalid sample counts')
        last = dt.date.fromisoformat(c['latest_game_date'])
        expected_rest = (tip.astimezone(ZoneInfo('America/New_York')).date()-last).days-1
        if last >= source_time.astimezone(dt.timezone.utc).date() or expected_rest < 0:
            raise ValueError('Nonhistorical team context')
        if type(c['rest_days_uncapped']) is not int or c['rest_days_uncapped'] != expected_rest:
            raise ValueError('Rest days inconsistent with dates')
        means = {}
        for period in ('season','last10'):
            means[period] = {}
            for metric in METRICS:
                value = c[period+'_mean_per_game'][metric]
                if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
                    raise ValueError('Invalid team metric')
                means[period][metric] = value
            means[period]['net_rating'] = means[period]['off_rating']-means[period]['def_rating']
        teams[side] = {'team':f[side],'team_id':c['team_id'],'season_games':n,'last10_games':last_n,
            'latest_game_date':last.isoformat(),'rest_days':expected_rest,'means':means,
            'last10_minus_season':{m:means['last10'][m]-means['season'][m] for m in (*METRICS,'net_rating')}}
    contrasts = {period:{m:teams['home']['means'][period][m]-teams['away']['means'][period][m]
                         for m in (*METRICS,'net_rating')} for period in ('season','last10')}
    home,away = f['home'],f['away']
    notes = []
    for period,label in (('season','Saison'),('last10','letzte Spiele')):
        d = contrasts[period]
        notes.append(f"{label}: {home} minus {away}: Offensivrating {d['off_rating']:+.3f}, Defensivrating {d['def_rating']:+.3f}, Nettorating {d['net_rating']:+.3f}, Pace {d['pace']:+.3f}. Beim Defensivrating ist niedriger guenstiger.")
    for side in ('home','away'):
        t = teams[side]
        change = t['last10_minus_season']
        notes.append(f"{t['team']}: letzte {t['last10_games']} gegen Saison ({t['season_games']} Spiele): Offensivrating {change['off_rating']:+.3f}, Defensivrating {change['def_rating']:+.3f}; Ruhetage {t['rest_days']}.")
    if any(t['rest_days']==0 for t in teams.values()):
        notes.append('Mindestens ein Team spielt laut Quelldaten an aufeinanderfolgenden Tagen; kein erfundener Punkteabschlag.')
    s,l = (contrasts[p]['net_rating'] for p in ('season','last10'))
    if s*l < 0:
        notes.append('Saison und juengere Teilstichprobe zeigen unterschiedliche Vorzeichen im Nettorating-Vergleich.')
    return {'game_id':f['game_id'],'home':home,'away':away,'start_time_utc':f['start_time_utc'],
        'status':'descriptive_team_analysis_only','teams':teams,'home_minus_away':contrasts,'findings':notes,
        'market_implications':{
            'moneyline':'Deskriptiver Teamvergleich vorhanden; keine unabhaengige Siegchance nachgewiesen.',
            'spread':'Nettorating-Differenz ist weder erwartete Siegmarge noch Handicap-Wahrscheinlichkeit.',
            'total':'Pace und Effizienz getrennt ausgewiesen; kein Total oder Ueber/Unter-p aus Mittelwerten erfunden.'},
        'missing':['current_personnel_and_replacement_roles','opponent_adjustment_and_schedule_strength',
                   'travel_and_home_away_splits','independent_line_probabilities','offer_bound_rules_and_price_assessment'],
        'model_input_approved':False,'betting_release':False,'recommendation':None}


def build(root, now):
    root = Path(root)
    paper = json.loads((root/'paper_latest.json').read_text())
    index = json.loads((root/'chat_index.json').read_text())
    generation,protocol = paper['generated_at_utc'],paper['protocol']
    if paper.get('execution_ok') is not True or index.get('execution_ok') is not True:
        raise ValueError('Upstream execution failed')
    if paper.get('money_betting_released') is not False or index.get('betting_release') is not False:
        raise ValueError('Unexpected upstream release')
    if any(index.get(k)!=paper[k] for k in ('generated_at_utc','protocol')):
        raise ValueError('Index snapshot mismatch')
    forecasts = paper['forecasts']
    ids = [f['game_id'] for f in forecasts]
    ix = [f['game_id'] for f in index['fixtures']]
    if len(ids)!=len(set(ids)) or len(ix)!=len(set(ix)) or set(ids)!=set(ix):
        raise ValueError('Fixture set mismatch')
    entries = {f['game_id']:f for f in index['fixtures']}
    output = []
    for f in forecasts:
        gid = f['game_id']
        try:
            if not re.fullmatch(r'002\d{7}',gid) or entries[gid]['context_path'] != f'reports/chat/{gid}.json':
                raise ValueError('Unsafe context path')
            body = (root/'chat'/f'{gid}.json').read_bytes()
            entry = analyze(json.loads(body),f,generation,protocol,now)
            entry['context_path'] = entries[gid]['context_path']
            entry['context_sha256'] = hashlib.sha256(body).hexdigest()
            output.append(entry)
        except Exception as exc:
            output.append({'game_id':gid,'status':'context_error','error':str(exc)[:400],'betting_release':False})
    return {'schema':'team-analysis-v1','generated_at_utc':now.isoformat(),'source_generated_at_utc':generation,
        'protocol':protocol,'execution_ok':all(r['status']!='context_error' for r in output),
        'method':'Unweighted per-game source means; not possession-weighted, opponent-adjusted or independent validation. Last10 is a subset of season, not independent confirmation.',
        'fixtures':output,'analysis_complete':False,'betting_release':False,
        'run_id':os.environ.get('GITHUB_RUN_ID'),'source_commit_sha':os.environ.get('GITHUB_SHA')}


def main():
    now = dt.datetime.now(dt.timezone.utc)
    try:
        report = build(Path('reports'),now)
    except Exception as exc:
        report = {'schema':'team-analysis-v1','generated_at_utc':now.isoformat(),'execution_ok':False,
                  'error':str(exc)[:400],'fixtures':[],'analysis_complete':False,'betting_release':False}
    folder = Path('team-analysis-results')
    folder.mkdir(exist_ok=True)
    (folder/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    lines = ['# Automatische Team-Grundanalyse','', 'Teilbaustein, keine abgeschlossene Marktanalyse oder Empfehlung.','']
    if report.get('error'):
        lines.append('Fehler: '+report['error'])
    for f in report['fixtures']:
        lines += ['## '+f['game_id']+' - '+f.get('away','?')+' bei '+f.get('home','?'),f['status'],'']
        lines += f.get('findings',[])
        lines += list(f.get('market_implications',{}).values())
        if f.get('error'):
            lines.append('Fehler: '+f['error'])
        lines.append('')
    (folder/'result.md').write_text('\n\n'.join(lines)+'\n')
    return 0 if report['execution_ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
