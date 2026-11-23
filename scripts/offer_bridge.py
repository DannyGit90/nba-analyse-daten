"""Bind observed offers to analysis evidence; no probabilities, colors or recommendations."""
import copy
import datetime as dt
import json
import math
import re
from collections import Counter
from pathlib import Path
from team_analysis import stamp

SIDES = {'moneyline':{'home','away'},'spread':{'home','away'},'total':{'over','under'}}
FIXTURE_LIMIT = 30
OFFER_LIMIT = 2000


def number(value):
    return type(value) in (int,float) and math.isfinite(value)


def read_json(path):
    body = Path(path).read_bytes()
    if len(body)>3000000:
        raise ValueError('Source file exceeds byte limit')
    return json.loads(body)


def load_offers(root, game_id, header):
    if not re.fullmatch(r'002\d{7}',game_id):
        raise ValueError('Invalid game ID')
    context = read_json(Path(root)/'chat'/(game_id+'.json'))
    if any(context.get(k)!=header[k] for k in header) or context['fixture']['game_id']!=game_id:
        raise ValueError('Context snapshot mismatch')
    offers,seen = [],set()
    for path in context['market_pages']:
        if path in seen or not re.fullmatch(r'reports/chat/'+game_id+r'-markets-\d+\.json',path):
            raise ValueError('Unsafe or duplicate market page path')
        seen.add(path)
        page = read_json(Path(root)/path.removeprefix('reports/'))
        if any(page.get(k)!=header[k] for k in header):
            raise ValueError('Market page snapshot mismatch')
        for offer in page['offers']:
            if offer.get('game_id')!=game_id:
                raise ValueError('Offer game mismatch')
            offers.append(offer)
        if len(offers)>OFFER_LIMIT:
            raise ValueError('Offer resource limit exceeded')
    return offers


def validate(offer):
    market,side = offer.get('market'),offer.get('side')
    if market not in SIDES or side not in SIDES[market]:
        raise ValueError('Unsupported market or side')
    if not number(offer.get('odds')) or offer['odds']<=1:
        raise ValueError('Invalid decimal odds')
    line = offer.get('line')
    if (market=='moneyline')!=(line is None) or (line is not None and not number(line)):
        raise ValueError('Invalid line for market')
    if offer.get('betting_release') is not False or offer.get('recommendation') is not None:
        raise ValueError('Unexpected release or recommendation')
    if not isinstance(offer.get('bookmaker'),str) or not offer['bookmaker'].strip():
        raise ValueError('Missing bookmaker')
    stamp(offer['observed_at_utc'])


def group_offers(offers, tip, now):
    groups = {}
    for offer in offers:
        validate(offer)
        groups.setdefault((offer['market'],offer['side'],offer['line']),[]).append(offer)
    selections = []
    for (market,side,line),items in sorted(groups.items(),key=lambda kv:(kv[0][0],kv[0][1],-1e9 if kv[0][2] is None else kv[0][2])):
        providers = Counter(o['bookmaker'] for o in items)
        best = max(o['odds'] for o in items)
        ps = sorted({o['p_experimental'] for o in items if number(o.get('p_experimental'))})
        gaps = ['independent_line_probability_missing','calibration_unvalidated']
        if any(o.get('rules_verified') is not True for o in items):
            gaps.append('offer_rules_unverified')
        if any(o.get('price_timestamp_utc') is None for o in items):
            gaps.append('price_time_unknown')
        if line is not None and float(line).is_integer():
            gaps.append('integer_line_push_rules')
        if any(o.get('calculation_status')!='computed_reference_only' for o in items):
            gaps.append('paper_calculation_missing')
        if any(stamp(o['observed_at_utc'])>=tip for o in items):
            gaps.append('observed_at_or_after_start')
        if any(count>1 for count in providers.values()):
            gaps.append('duplicate_provider_rows')
        if len(providers)==1:
            gaps.append('single_provider_reference')
        if len(ps)>1:
            gaps.append('inconsistent_paper_probability')
        selections.append({'market':market,'side':side,'line':line,'provider_count':len(providers),
            'best_odds':best,'best_bookmakers':sorted({o['bookmaker'] for o in items if o['odds']==best}),
            'oldest_observation_age_minutes':max((now-stamp(o['observed_at_utc'])).total_seconds()/60 for o in items),
            'prices':[{k:o.get(k) for k in ('bookmaker','odds','observed_at_utc','price_status','price_timestamp_utc','rules_verified','calculation_status','source')} for o in items],
            'paper_reference':{'p_experimental':ps[0] if len(ps)==1 else None,'validated':False,'usable_for_filter':False},
            'gaps':gaps,
            'assessment':{'status':'UNGEPRUEFT','reason':'no independent line probability or validated calibration','color':None,'recommendation':None}})
    return selections


def side_context(game, side):
    people = game.get('personnel',{}).get(side,{})
    review = game.get('replacement_review',{}).get(side,{})
    records = people.get('records',[])
    result = {'personnel_status':people.get('status','missing'),
        'reported_status_counts':dict(Counter(r['reported_status'] for r in records)),
        'unresolved_identity_names':[r['source_name'] for r in records if r.get('database_match_verified') is not True],
        'rest_days':game['teams'][side]['rest_days'],
        'reported_out_recorded_fga_share':0.0,'reported_out_without_profile':0,
        'conditional_recorded_fga_share':0.0,'conditional_without_profile':0,
        'candidate_names':[p['source_name'] for p in review.get('players',[]) if p.get('candidate_for_further_role_review')],
        'share_note':'Shares are recorded attempt shares of named players in the selected recent window; they are not expected loss or impact.'}
    for p in review.get('players',[]):
        for key,evidence in (('reported_out','reported_out'),('conditional','conditional')):
            if p.get('availability_evidence')==evidence:
                if p.get('recorded_fga_share') is None:
                    result[key+'_without_profile'] += 1
                else:
                    result[key+'_recorded_fga_share'] += p['recorded_fga_share']
    return result


def build(report, root, now):
    if len(report['fixtures'])>FIXTURE_LIMIT:
        raise ValueError('Fixture resource limit exceeded')
    paper = read_json(Path(root)/'paper_latest.json')
    header = {'generated_at_utc':paper['generated_at_utc'],'protocol':paper['protocol']}
    if report.get('source_generated_at_utc')!=header['generated_at_utc'] or report.get('protocol')!=header['protocol']:
        raise ValueError('Analysis and market snapshot mismatch')
    result = copy.deepcopy(report)
    result['offer_bridge'] = {'status':'blocked','errors':[],'games_bound':0,'selection_count':0,'analysis_complete':False}
    if report.get('replacement_review',{}).get('status') not in ('evidence_screen_only','no_pregame_teams'):
        result['offer_bridge']['errors'].append({'game_id':None,'error':'Replacement evidence screen unavailable'})
        return result
    for game in result['fixtures']:
        if game['status']!='descriptive_team_analysis_only':
            continue
        try:
            tip = stamp(game['start_time_utc'])
            if tip<=now:
                game['offer_bridge'] = {'status':'started_not_assessed'}
                continue
            selections = group_offers(load_offers(root,game['game_id'],header),tip,now)
            game['offer_bridge'] = {'status':'offers_bound_unassessed','selection_count':len(selections),
                'team_context':{side:side_context(game,side) for side in ('home','away')},
                'game_gaps':['role_assessment_incomplete','opponent_adjustment_missing','independent_line_probabilities_missing'],
                'selections':selections}
            result['offer_bridge']['games_bound'] += 1
            result['offer_bridge']['selection_count'] += len(selections)
        except Exception as exc:
            error = str(exc)[:400]
            game['offer_bridge'] = {'status':'unavailable','error':error}
            result['offer_bridge']['errors'].append({'game_id':game['game_id'],'error':error})
    state = result['offer_bridge']
    state['status'] = 'partial_failure' if state['errors'] else 'offers_bound_unassessed' if state['games_bound'] else 'no_pregame_games'
    return result


def main():
    import replacement_review
    replacement_review.main()
    folder = Path('team-analysis-results')
    report = json.loads((folder/'result.json').read_text())
    try:
        report = build(report,Path('reports'),dt.datetime.now(dt.timezone.utc))
    except Exception as exc:
        report['offer_bridge'] = {'status':'failed','error':str(exc)[:400],'analysis_complete':False}
    (folder/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False,default=str)+'\n')
    summary = json.loads((folder/'summary.json').read_text())
    summary['offer_bridge'] = report['offer_bridge']
    for item in summary['fixtures']:
        game = next(g for g in report['fixtures'] if g['game_id']==item['game_id'])
        bridge = game.get('offer_bridge',{})
        item['offer_bridge'] = {'status':bridge.get('status'),'selection_count':bridge.get('selection_count'),'error':bridge.get('error'),
            'team_context':bridge.get('team_context')}
    (folder/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    lines = ['','## Angebote mit belegten Befunden und Luecken: keine Bewertung, keine Empfehlung']
    for game in report['fixtures']:
        bridge = game.get('offer_bridge')
        if not bridge or bridge.get('status')!='offers_bound_unassessed':
            continue
        lines += ['### '+game['game_id']+' '+game['away']+' bei '+game['home'],
            '| Markt | Seite | Linie | Anbieter | Bestquote | Offene Luecken |','|---|---|---|---|---|---|']
        for s in bridge['selections']:
            lines.append('| '+' | '.join(str(v) for v in (s['market'],s['side'],'-' if s['line'] is None else s['line'],s['provider_count'],s['best_odds'],', '.join(s['gaps'])))+' |')
    with (folder/'result.md').open('a') as f:
        f.write('\n\n'.join(lines)+'\n')
    return 0 if report.get('execution_ok') is True and report['offer_bridge']['status'] in ('offers_bound_unassessed','no_pregame_games') else 1


if __name__ == '__main__':
    raise SystemExit(main())
