import datetime as dt
import json
from pathlib import Path
import duckdb
import numpy as np
from probability_profile import selection_profile

PROTOCOL = 'season-prior10-paper-v1'
now = dt.datetime.now(dt.timezone.utc)
report = {'protocol': PROTOCOL, 'checked_at_utc': now.isoformat(), 'execution_ok': False, 'status': 'prospective_paper_only', 'betting_release': False, 'selection_rule': 'Earliest stored pregame forecast per game; no retrospective forecasts inserted.', 'limitations': ['Wilson intervals are approximate subgroup-rate intervals, not individual prediction guarantees; dependence between games is not modelled.', 'No automatic betting release, profitability proof or injury adjustment.', 'Results must have two internally consistent completed team-log rows.', 'Archived scheduled tip-off is the timestamp check; historical actual tip-off changes are not independently reconstructed.']}
try:
    first = {}
    for path in sorted(Path('paper_log').glob('*.json')):
        snapshot = json.loads(path.read_text())
        if snapshot.get('protocol') != PROTOCOL or not snapshot.get('execution_ok'):
            continue
        stamp = dt.datetime.fromisoformat(snapshot['generated_at_utc'])
        for f in snapshot.get('forecasts', []):
            start = dt.datetime.fromisoformat(f['start_time_utc'])
            if stamp < start:
                first.setdefault(f['game_id'], dict(f, archived_at_utc=stamp.isoformat()))
    report['unique_games_archived'] = len(first)
    seasons = sorted({dt.datetime.fromisoformat(f['start_time_utc']).year + int(dt.datetime.fromisoformat(f['start_time_utc']).month >= 10) for f in first.values()})
    actual = {}
    if seasons:
        con = duckdb.connect()
        con.execute("ATTACH 'https://basketball-data.billmill.org/nba/nba.duckdb' AS nba")
        placeholders = ','.join('?' for _ in seasons)
        rows = con.execute('SELECT game_id, team_id, opp_team_id, home, pts FROM nba.team_game_logs WHERE season IN (' + placeholders + ')', seasons).fetchall()
        con.close()
        for gid, team, opp, home, pts in rows:
            if str(gid) in first:
                actual.setdefault(str(gid), []).append({'team': str(team), 'opp': str(opp), 'home': home, 'pts': pts})
    scored = []
    pending = 0
    invalid = []
    for gid, f in first.items():
        if dt.datetime.fromisoformat(f['start_time_utc']) > now:
            pending += 1
            continue
        rows = actual.get(gid, [])
        if not rows:
            pending += 1
            continue
        home = [r for r in rows if r['team'] == f['home_team_id'] and r['opp'] == f['away_team_id'] and r['home'] is True]
        away = [r for r in rows if r['team'] == f['away_team_id'] and r['opp'] == f['home_team_id'] and r['home'] is False]
        if len(rows) != 2 or len(home) != 1 or len(away) != 1 or home[0]['pts'] is None or away[0]['pts'] is None or home[0]['pts'] == away[0]['pts']:
            invalid.append({'game_id': gid, 'reason': 'Missing or ambiguous home/away pair, missing points or tied final'})
            continue
        p, pb = float(f['p_home_experimental']), float(f['baseline_home_probability'])
        if not (0 <= p <= 1 and 0 <= pb <= 1):
            raise ValueError('Invalid archived probability')
        margin = float(home[0]['pts'] - away[0]['pts'])
        total = float(home[0]['pts'] + away[0]['pts'])
        won = int(margin > 0)
        mi, ti = f['margin_interval80'], f['total_interval80']
        scored.append({'p': p, 'won': won, 'pb': pb, 'margin_error': abs(float(f['home_margin_point']) - margin), 'total_error': abs(float(f['total_point']) - total), 'margin_covered80': int(mi[0] <= margin <= mi[1]), 'total_covered80': int(ti[0] <= total <= ti[1])})
    def group(records, favorite=False):
        n = len(records)
        if not n:
            return {'n': 0, 'mean_probability': None, 'observed_win_rate': None, 'observed_rate_wilson95': None, 'brier': None}
        p = np.array([max(r['p'], 1 - r['p']) if favorite else r['p'] for r in records])
        y = np.array([(r['won'] if r['p'] >= .5 else 1 - r['won']) if favorite else r['won'] for r in records])
        rate = float(y.mean())
        z = 1.959963984540054
        den = 1 + z * z / n
        center = (rate + z * z / (2 * n)) / den
        half = z * np.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / den
        return {'n': n, 'mean_probability': float(p.mean()), 'observed_win_rate': rate, 'mean_probability_minus_observed': float(p.mean() - rate), 'observed_rate_wilson95': [float(center - half), float(center + half)], 'brier': float(np.mean((p - y) ** 2))}
    report.update(games_scored=len(scored), games_waiting_for_results=pending, invalid_result_pairs=invalid, metrics=None)
    if scored:
        report['metrics'] = {'model_brier': float(np.mean([(r['p'] - r['won']) ** 2 for r in scored])), 'baseline_brier': float(np.mean([(r['pb'] - r['won']) ** 2 for r in scored])), 'margin_abs_error': float(np.mean([r['margin_error'] for r in scored])), 'total_abs_error': float(np.mean([r['total_error'] for r in scored])), 'margin_coverage80': float(np.mean([r['margin_covered80'] for r in scored])), 'total_coverage80': float(np.mean([r['total_covered80'] for r in scored]))}
    report['calibration_home'] = []
    for lo, hi in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.000001)]:
        stats = group([r for r in scored if lo <= r['p'] < hi])
        stats.update(lo=lo, hi=min(hi, 1))
        report['calibration_home'].append(stats)
    report['original_warning_home_over80'] = group([r for r in scored if r['p'] >= .8])
    report['favorite_over80_either_side'] = group([r for r in scored if max(r['p'], 1 - r['p']) >= .8], favorite=True)
    report['favorite_selection_profile'] = selection_profile(scored, group)
    report['execution_ok'] = True
except Exception as exc:
    report.update(error_type=type(exc).__name__, error=str(exc)[:6000])
Path('reports').mkdir(exist_ok=True)
Path('reports/paper_evaluation.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
print(json.dumps(report, indent=2, allow_nan=False))
