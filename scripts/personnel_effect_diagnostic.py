"""Read-only diagnostic: forward-tested with/without-player margin effects.

Paper diagnostic only. No model input, no release, no repository writes.
Absence means a rotation player has no player-log row in a game; it is not
labelled as injury. Home court is not modelled in the baseline.
"""
import json
import sys
import datetime as dt
from collections import defaultdict, deque

PRIOR = 10
WINDOW = 15
MIN_APPEARANCES = 5
MIN_MEAN_FGA = 8.0
K_CANDIDATES = (5, 10, 20, 40)
DEV_END_SEASON = 2022


def build_games(team_rows):
    by = defaultdict(dict)
    for r in team_rows:
        by[r['game_id']][r['team_id']] = r
    games = []
    for gid, d in by.items():
        if len(d) != 2:
            continue
        (a, ra), (b, rb) = sorted(d.items())
        if ra['opp_team_id'] != b or rb['opp_team_id'] != a or ra['pts'] == rb['pts']:
            continue
        games.append({'game_id': gid, 'date': str(ra['game_date']), 'season': ra['season'],
                      'a': a, 'b': b, 'margin_a': ra['pts'] - rb['pts']})
    games.sort(key=lambda g: (g['date'], g['game_id']))
    return games


def build_appearances(player_rows):
    out = defaultdict(lambda: defaultdict(dict))
    for r in player_rows:
        fga = r['fga'] if r['fga'] is not None else 0
        out[r['game_id']][r['team_id']][r['player_id']] = fga
    return out


def rotation(history):
    seen = defaultdict(list)
    for game in history:
        for pid, fga in game.items():
            seen[pid].append(fga)
    return {p for p, v in seen.items() if len(v) >= MIN_APPEARANCES and sum(v) / len(v) >= MIN_MEAN_FGA}


def simulate(games, appear, k):
    margins = defaultdict(lambda: [0.0, 0])
    prev_mean = defaultdict(float)
    season = None
    recent = defaultdict(lambda: deque(maxlen=WINDOW))
    stats = defaultdict(lambda: [0.0, 0, 0.0, 0])
    records = []

    def strength(team):
        s, n = margins[team]
        return (s + PRIOR * prev_mean[team]) / (n + PRIOR)

    def effect(team, pid):
        sa, na, sp, np_ = stats[(team, pid)]
        if na < 1 or np_ < 1:
            return 0.0
        return na / (na + k) * (sa / na - sp / np_)

    for g in games:
        if g['season'] != season:
            if season is not None:
                for t, (s, n) in list(margins.items()):
                    if n:
                        prev_mean[t] = s / n
            margins.clear()
            season = g['season']
        a, b = g['a'], g['b']
        if g['game_id'] not in appear:
            continue
        play = appear[g['game_id']]
        if a not in play or b not in play:
            continue
        base = strength(a) - strength(b)
        absent, adj = {}, {}
        for t in (a, b):
            rot = rotation(recent[t])
            absent[t] = sorted(rot - set(play[t]))
            adj[t] = sum(effect(t, p) for p in absent[t])
        pred_adj = base + adj[a] - adj[b]
        records.append({'season': g['season'], 'actual': g['margin_a'], 'base': base, 'adjusted': pred_adj,
                        'absent_players': len(absent[a]) + len(absent[b])})
        resid = g['margin_a'] - base
        for t, r in ((a, resid), (b, -resid)):
            rot = rotation(recent[t])
            for p in rot:
                st = stats[(t, p)]
                if p in play[t]:
                    st[2] += r
                    st[3] += 1
                else:
                    st[0] += r
                    st[1] += 1
            recent[t].append(dict(play[t]))
        margins[a][0] += g['margin_a']
        margins[a][1] += 1
        margins[b][0] -= g['margin_a']
        margins[b][1] += 1
    return records


def mae(records, key):
    return sum(abs(r['actual'] - r[key]) for r in records) / len(records) if records else None


def summarize(records):
    out = {'games': len(records), 'mae_baseline': mae(records, 'base'), 'mae_adjusted': mae(records, 'adjusted')}
    with_abs = [r for r in records if r['absent_players'] > 0]
    out['games_with_rotation_absence'] = len(with_abs)
    out['mae_baseline_with_absence'] = mae(with_abs, 'base')
    out['mae_adjusted_with_absence'] = mae(with_abs, 'adjusted')
    return out


def evaluate(games, appear):
    results = {}
    for k in K_CANDIDATES:
        recs = simulate(games, appear, k)
        dev = [r for r in recs if r['season'] <= DEV_END_SEASON]
        test = [r for r in recs if r['season'] > DEV_END_SEASON]
        results[k] = {'development': summarize(dev), 'test': summarize(test)}
    usable = {k: v for k, v in results.items() if v['development']['mae_adjusted'] is not None}
    chosen = min(usable, key=lambda k: usable[k]['development']['mae_adjusted']) if usable else None
    return {'candidates': {str(k): v for k, v in results.items()}, 'chosen_shrinkage_k': chosen,
            'selection_rule': 'lowest development MAE (seasons <= %d); test seasons not used for selection' % DEV_END_SEASON}


def main():
    import duckdb
    first = 2016
    con = duckdb.connect()
    con.execute("ATTACH 'https://basketball-data.billmill.org/nba/nba.duckdb' AS nba (READ_ONLY)")
    cur = con.execute("SELECT season,game_id,team_id,opp_team_id,game_date,pts FROM nba.main.team_game_logs WHERE season>=? AND game_id LIKE '002%'", [first])
    cols = [c[0] for c in cur.description]
    team_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur = con.execute("SELECT game_id,team_id,player_id,fga FROM nba.main.player_game_logs WHERE season>=? AND game_id LIKE '002%'", [first])
    cols = [c[0] for c in cur.description]
    player_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    con.close()
    games = build_games(team_rows)
    report = {'schema': 'personnel-effect-diagnostic-v1', 'generated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'execution_ok': True, 'betting_release': False, 'model_input_approved': False,
              'validated': False, 'games_loaded': len(games),
              'params': {'prior': PRIOR, 'window': WINDOW, 'min_appearances': MIN_APPEARANCES,
                         'min_mean_fga': MIN_MEAN_FGA, 'dev_end_season': DEV_END_SEASON},
              'limitations': ['Absence = no player-log row for a rotation player; not verified injury.',
                              'Baseline has no home-court term and no minutes data.',
                              'Effects are additive; overlapping roles are not separated.',
                              'Diagnostic only: an improvement does not release betting or change any model.'],
              'evaluation': evaluate(games, build_appearances(player_rows))}
    path = sys.argv[1] if len(sys.argv) > 1 else 'personnel-effect-results/result.json'
    import os
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as f:
        json.dump(report, f, indent=2, allow_nan=False)
        f.write('\n')


if __name__ == '__main__':
    main()
