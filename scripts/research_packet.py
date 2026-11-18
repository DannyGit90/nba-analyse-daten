import copy
import datetime as dt
import json
import math
import runpy
from pathlib import Path

SCHEMA = 'research-packet-v1'
SOURCE = 'https://basketball-data.billmill.org/nba/nba.duckdb'
RATINGS = ('off_rating', 'def_rating', 'pace')


def finite(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a measurement')
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Non-finite measurement')
    return number


def team_summary(rows, team, season, target_date):
    target = dt.date.fromisoformat(str(target_date)[:10])
    rows = [r for r in rows if str(r['team_id']) == team
            and int(r['season']) == season
            and dt.date.fromisoformat(str(r['game_date'])[:10]) < target]
    rows = sorted(rows, key=lambda r: (str(r['game_date']), str(r['game_id'])))
    if len(rows) < 3 or len({str(r['game_id']) for r in rows}) != len(rows):
        raise ValueError('Insufficient or duplicate team games')
    for r in rows:
        if any(finite(r[c]) <= 0 for c in RATINGS):
            raise ValueError('Invalid team rating')
    recent = rows[-10:]
    def means(sample):
        return {c: sum(finite(r[c]) for r in sample) / len(sample) for c in RATINGS}
    latest = str(rows[-1]['game_date'])[:10]
    rest = max(0, (target - dt.date.fromisoformat(latest)).days - 1)
    return {'team_id': team, 'season_games': len(rows), 'last10_games': len(recent),
            'latest_game_date': latest, 'rest_days_uncapped': rest,
            'rest_days_model_capped7': min(7, rest),
            'season_mean_per_game': means(rows), 'last10_mean_per_game': means(recent),
            'recent_games': [{'game_id': str(r['game_id']), 'date': str(r['game_date'])[:10],
                              'opponent_id': str(r['opp_team_id']), 'points': finite(r['pts'])}
                             for r in recent]}


def half_point_probability(point, residuals, market, side, line):
    point, line = finite(point), finite(line)
    errors = [finite(x) for x in residuals]
    if len(errors) < 200:
        raise ValueError('Insufficient historical forward errors')
    if not (line * 2).is_integer() or line.is_integer():
        raise ValueError('Only half-point lines supported; no integer or quarter lines')
    if market == 'spread' and side in ('home', 'away'):
        values = [(point + x) * (1 if side == 'home' else -1) + line for x in errors]
    elif market == 'total' and side in ('over', 'under') and line > 0:
        values = [((point + x) - line) * (1 if side == 'over' else -1) for x in errors]
    else:
        raise ValueError('Unsupported market or selection')
    if any(x == 0 for x in values):
        raise ValueError('Empirical draw on half-point boundary requires review')
    return sum(x > 0 for x in values) / len(values)


def paper_price(probability, decimal_odds):
    p, q = finite(probability), finite(decimal_odds)
    if not 0 <= p <= 1 or q <= 1:
        raise ValueError('Invalid probability or decimal odds')
    return {'p_experimental': p, 'break_even': 1 / q,
            'paper_fair_odds': 1 / p if p else None,
            'paper_ev': p * q - 1, 'betting_release': False,
            'status': 'uncalibrated_paper_only_not_a_recommendation'}


def build(ns):
    p = ns['report']
    stamp = p['generated_at_utc']
    result = {'schema': SCHEMA, 'generated_at_utc': stamp, 'protocol': p['protocol'],
              'execution_ok': False, 'betting_release': False, 'source': SOURCE,
              'markets_linked': False, 'fixtures': [],
              'limitations': ['Means of per-game ratings, not possession-weighted aggregates.',
                             'No opponent adjustment or quantified injury correction.',
                             'No bookmaker feed or offer validation; no recommendations.']}
    distribution = {'schema': SCHEMA, 'generated_at_utc': stamp, 'protocol': p['protocol'],
                    'available': False, 'betting_release': False,
                    'limitations': ['Pooled historical forward errors; not calibrated for spread/total lines.',
                                    'Only half-point lines; no push estimate. Match timestamps and protocol.',
                                    'Future error distribution may differ; no profitability validation.']}
    if p.get('execution_ok') is not True:
        raise ValueError('Source paper execution failed')
    if not p['forecasts']:
        result.update(execution_ok=True, status='no_available_forecasts')
        return result, distribution
    if p.get('completed_schedule_games_missing_from_logs'):
        raise ValueError('Freshness gate must not be bypassed')
    data = ns['data']
    rows = data[data.season == ns['current']].to_dict('records')
    schedule = {str(g.game_id): g for g in ns['upcoming'].itertuples()}
    for f in p['forecasts']:
        g = schedule[f['game_id']]
        if str(g.home_team_id) != f['home_team_id'] or str(g.away_team_id) != f['away_team_id']:
            raise ValueError('Schedule and forecast team IDs disagree')
        fixture = {'game_id': f['game_id'], 'start_time_utc': f['start_time_utc'],
                   'home': f['home'], 'away': f['away'],
                   'home_margin_point': f['home_margin_point'], 'total_point': f['total_point']}
        for side in ('home', 'away'):
            team = f[side + '_team_id']
            summary = team_summary(rows, team, ns['current'], g.game_date)
            summary['model_features'] = dict(zip(ns['features'],
                map(float, ns['future_features'](team, g.game_date))))
            fixture[side + '_context'] = summary
        result['fixtures'].append(fixture)
    result.update(execution_ok=True, status='statistics_ready_markets_unlinked')
    errors = ns['residuals']
    if len(errors) < 200:
        raise ValueError('Insufficient residual sample')
    distribution.update(available=True, residual_n=len(errors),
                        margin_residuals=[finite(x) for x in errors[:, 0]],
                        total_residuals=[finite(x) for x in errors[:, 1]])
    return result, distribution


def enrich_latest(paper, packet):
    if packet.get('execution_ok') is not True:
        raise ValueError('Research export failed')
    for key in ('generated_at_utc', 'protocol'):
        if paper.get(key) != packet.get(key):
            raise ValueError('Research and paper snapshots disagree')
    contexts = {f['game_id']: f for f in packet['fixtures']}
    if set(contexts) != {f['game_id'] for f in paper['forecasts']}:
        raise ValueError('Research and forecast fixture sets disagree')
    enriched = copy.deepcopy(paper)
    for f in enriched['forecasts']:
        for side in ('home', 'away'):
            f[side + '_context'] = contexts[f['game_id']][side + '_context']
    enriched['research_extension'] = {
        'schema': SCHEMA, 'markets_linked': False,
        'packet_path': 'reports/research_packet.json',
        'distribution_path': 'reports/paper_distribution.json',
        'limitations': packet['limitations']}
    return enriched


def main():
    Path('reports').mkdir(exist_ok=True)
    try:
        ns = runpy.run_path(str(Path(__file__).with_name('paper_monitor.py')))
        packet, distribution = build(ns)
        enriched = enrich_latest(ns['report'], packet)
        Path('reports/paper_latest.json').write_text(json.dumps(enriched, indent=2, allow_nan=False) + '\n')
    except Exception as exc:
        packet = {'schema': SCHEMA, 'execution_ok': False, 'betting_release': False,
                  'markets_linked': False, 'fixtures': [], 'error': str(exc)}
        distribution = {'schema': SCHEMA, 'available': False, 'betting_release': False,
                        'error': str(exc)}
    Path('reports').mkdir(exist_ok=True)
    for name, payload in [('research_packet.json', packet), ('paper_distribution.json', distribution)]:
        Path('reports', name).write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
