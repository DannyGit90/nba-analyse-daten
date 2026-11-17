import datetime as dt
import json
import runpy
import traceback
from pathlib import Path
import numpy as np
import pandas as pd

now = dt.datetime.now(dt.timezone.utc)
report = {'created_at_utc': now.isoformat(), 'execution_ok': False, 'production_model_changed': False, 'money_betting_released': False, 'repair_validated': False, 'status': 'structural_repair_candidate_only', 'method': 'Shrink pregame season-average offense, defense and pace toward the same franchise previous full season. Prior strength selected only on 2018-2023 forward Brier score from fixed candidates [0,5,10,20,40]. Last10 and rest features unchanged. Monthly forward fits and prior-365-day empirical errors match frozen baseline. No sigmoid calibration.', 'limitations': ['Design motivated by already inspected recent data; 2024 onward are diagnostic checks, not pristine holdouts.', 'Previous franchise season does not account for offseason roster changes.', 'No injury corrections or bookmaker-price/profitability validation.', 'No handicap or total market probability calibration.', 'Future prospective confirmation remains required.', 'A failed repair is not grounds for arbitrary probability caps.']}
Path('reports').mkdir(exist_ok=True)
try:
    env = runpy.run_path('scripts/test_model.py')
    if not env['report']['execution_ok']:
        raise RuntimeError('Base model reproduction failed')
    d = env['data'].copy()
    games = env['games'].copy()
    X0, Y, names = env['X'], env['Y'], env['names']
    previous = d.groupby(['season', 'team_id'])[['off_rating', 'def_rating', 'pace']].mean().reset_index()
    previous['season'] += 1
    previous = previous.rename(columns={c: c + '_prior' for c in ['off_rating', 'def_rating', 'pace']})
    dates = d.groupby('season').game_date.agg(['min', 'max'])
    for season in dates.index:
        if season - 1 in dates.index and not dates.loc[season - 1, 'max'] < dates.loc[season, 'min']:
            raise ValueError('Overlapping source seasons: prior is not safely pregame')
    d = d.merge(previous, on=['season', 'team_id'], how='left', validate='many_to_one')
    grouped_months = []
    months = games.game_date.dt.to_period('M')
    for month in sorted(months.unique()):
        start = month.start_time
        te = np.flatnonzero((months == month).to_numpy())
        season = int(games.iloc[te[0]].season)
        tr = np.flatnonzero(((games.game_date < start) & (games.season >= season - 3)).to_numpy())
        if len(tr) >= 500:
            grouped_months.append((start, tr, te))
    def matrix(k):
        x = X0.copy()
        if k == 0:
            return x
        work = d.copy()
        for col in ['off_rating', 'def_rating', 'pace']:
            avg = work[col + '_season']
            prior = work[col + '_prior'].fillna(avg)
            work[col + '_adjusted'] = (work.prior_n * avg + k * prior) / (work.prior_n + k)
        indexed = work.set_index(['season', 'game_id', 'team_id'])
        for side in ['_h', '_a']:
            lookup = pd.MultiIndex.from_arrays([games.season, games.game_id, games['team_id' + side]], names=['season', 'game_id', 'team_id'])
            for col in ['off_rating', 'def_rating', 'pace']:
                x[:, names.index(col + '_season' + side)] = indexed[col + '_adjusted'].reindex(lookup).to_numpy(dtype=float)
        return x
    def forward(k):
        x = matrix(k)
        records = []
        for start, tr, te in grouped_months:
            assert games.iloc[tr].game_date.max() < games.iloc[te].game_date.min()
            model = env['fit'](x[tr], Y[tr])
            predicted = model.predict(x[te])
            older = [r for r in records if start - pd.Timedelta(days=365) <= r['date'] < start]
            if len(older) >= 200:
                em = np.array([r['margin_error'] for r in older])
                et = np.array([r['total_error'] for r in older])
                qm, qt = np.quantile(em, [.1, .9]), np.quantile(et, [.1, .9])
            for j, idx in enumerate(te):
                g = games.iloc[idx]
                row = {'date': g.game_date, 'season': int(g.season), 'won': int(Y[idx, 0] > 0), 'margin_error': float(Y[idx, 0] - predicted[j, 0]), 'total_error': float(Y[idx, 1] - predicted[j, 1])}
                if len(older) >= 200:
                    row.update(p=float(np.mean(predicted[j, 0] + em > 0)), margin_covered80=bool(qm[0] <= row['margin_error'] <= qm[1]), total_covered80=bool(qt[0] <= row['total_error'] <= qt[1]))
                records.append(row)
        return pd.DataFrame(records)
    all_results = {}
    development = []
    for k in [0, 5, 10, 20, 40]:
        result = forward(k)
        all_results[k] = result
        dev = result[result.season.between(2018, 2023)].dropna(subset=['p'])
        if len(dev) == 0:
            raise ValueError('No development predictions')
        development.append({'prior_strength': k, 'games': len(dev), 'brier': float(np.mean((dev.p - dev.won) ** 2))})
    raw = all_results[0]
    original = env['oos']
    if len(raw) != len(original) or not np.allclose(raw.p.to_numpy(), original.p_home.to_numpy(), equal_nan=True):
        raise ValueError('Unmodified candidate did not reproduce original forward probabilities')
    chosen = min(development, key=lambda r: (r['brier'], r['prior_strength']))['prior_strength']
    candidate = all_results[chosen]
    def summarize(z):
        pz = z.dropna(subset=['p'])
        out = {'games': len(z), 'probability_games': len(pz), 'margin_mae': float(z.margin_error.abs().mean()), 'total_mae': float(z.total_error.abs().mean())}
        if len(pz):
            out.update(brier=float(np.mean((pz.p - pz.won) ** 2)), margin_coverage80=float(pz.margin_covered80.mean()), total_coverage80=float(pz.total_covered80.mean()))
        return out
    def tail(z):
        z = z.dropna(subset=['p'])
        if len(z) == 0:
            return {'n': 0}
        return {'n': len(z), 'mean_probability': float(z.p.mean()), 'observed_win_rate': float(z.won.mean()), 'brier': float(np.mean((z.p - z.won) ** 2))}
    report['base_version'] = env['report']['version']
    report['development_candidates'] = development
    report['selected_prior_strength'] = chosen
    report['baseline_reproduced'] = True
    current = now.year + int(now.month >= 10)
    report['recent_comparison'] = {}
    for year in range(2024, current + 1):
        r = raw[raw.season == year]
        c = candidate[candidate.season == year]
        indices = r.index[r.p >= .8]
        report['recent_comparison'][str(year)] = {'baseline': summarize(r), 'candidate': summarize(c), 'same_original_over80_group': {'baseline': tail(r.loc[indices]), 'candidate': tail(c.loc[indices])}, 'candidate_own_over80_group': tail(c[c.p >= .8])}
    report['interpretation_rule'] = 'Selection uses older development data only. Improvement in inspected recent data is not a betting release. If strength=0 wins development, no prior modification is selected. Do not keep searching until the current 23 cases look good.'
    report['execution_ok'] = True
except Exception as exc:
    report.update(error_type=type(exc).__name__, error=str(exc)[:6000], traceback=traceback.format_exc()[-10000:])
Path('reports/season_prior_test.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
print(json.dumps(report, indent=2, allow_nan=False))
