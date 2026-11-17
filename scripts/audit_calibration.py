import datetime as dt
import json
import runpy
import traceback
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

now = dt.datetime.now(dt.timezone.utc)
report = {'created_at_utc': now.isoformat(), 'execution_ok': False, 'status': 'diagnostic_only_no_betting_release', 'production_model_changed': False, 'correction_proven': False, 'prospective_confirmation_required': True, 'method': 'Reproduce frozen base model. Fit a fixed sigmoid calibrator on earlier forward probabilities from preceding three calendar years, minimum 500. Refit monthly; never fit on evaluated month. C=1 fixed, no parameter search.', 'limitations': ['Recent seasons were already inspected, so this is a diagnostic comparison, not an untouched final test.', 'No validated injury adjustment; this audit cannot attribute errors to injuries.', 'No historical bookmaker or profitability validation.', 'No handicap/total calibration or automatic release.', 'Confidence intervals shown for subgroup observed rates do not include model uncertainty.', 'No schedule completeness proof.']}
Path('reports').mkdir(exist_ok=True)
try:
    env = runpy.run_path('scripts/test_model.py')
    base = env['report']
    if not base['execution_ok']:
        raise RuntimeError('Base model reproduction failed: ' + str(base.get('error')))
    z = env['oos'].copy().reset_index(drop=True)
    games = env['games'].copy()
    aligned = games[games.game_date >= pd.Timestamp(z.date.min())].reset_index(drop=True)
    if len(aligned) != len(z) or not np.allclose(aligned.margin, z.actual_margin) or not np.allclose(aligned.total, z.actual_total) or not np.array_equal(aligned.game_date.dt.strftime('%Y-%m-%d'), z.date):
        raise ValueError('Cannot align forward predictions with games; no guessed row attribution')
    for key in ['game_id', 'team_id_h', 'team_id_a', 'prior_n_h', 'prior_n_a']:
        z[key] = aligned[key].to_numpy()
    z['date'] = pd.to_datetime(z.date)
    z['won'] = (z.actual_margin > 0).astype(int)
    z['p_calibrated'] = np.nan
    z['calibration_train_n'] = 0
    def logits(p):
        p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p)).reshape(-1, 1)
    def fit_cal(tr):
        return LogisticRegression(C=1.0, solver='lbfgs', max_iter=1000).fit(logits(tr.p_home), tr.won)
    for month in sorted(z.date.dt.to_period('M').unique()):
        start = month.start_time
        tr = z[(z.date < start) & (z.date >= start - pd.DateOffset(years=3))].dropna(subset=['p_home'])
        mask = (z.date.dt.to_period('M') == month) & z.p_home.notna()
        if len(tr) < 500 or tr.won.nunique() < 2 or not mask.any():
            continue
        assert tr.date.max() < z.loc[mask, 'date'].min()
        cal = fit_cal(tr)
        z.loc[mask, 'p_calibrated'] = cal.predict_proba(logits(z.loc[mask, 'p_home']))[:, 1]
        z.loc[mask, 'calibration_train_n'] = len(tr)
    def observed_interval(wins, n):
        if not n:
            return None
        p = wins / n
        zz = 1.959963984540054
        den = 1 + zz * zz / n
        center = (p + zz * zz / (2 * n)) / den
        half = zz * np.sqrt(p * (1 - p) / n + zz * zz / (4 * n * n)) / den
        return [float(center - half), float(center + half)]
    def group_stats(g, col):
        g = g.dropna(subset=[col])
        if not len(g):
            return {'n': 0}
        n = len(g)
        wins = int(g.won.sum())
        return {'n': n, 'mean_probability': float(g[col].mean()), 'observed_win_rate': wins / n, 'observed_rate_wilson95': observed_interval(wins, n), 'brier': float(np.mean((g[col] - g.won) ** 2)), 'mean_probability_minus_observed': float(g[col].mean() - g.won.mean())}
    def evaluate(g):
        paired = g.dropna(subset=['p_home', 'p_calibrated', 'p_base'])
        out = {'paired_games': len(paired), 'raw': group_stats(paired, 'p_home'), 'calibrated': group_stats(paired, 'p_calibrated'), 'baseline': group_stats(paired, 'p_base')}
        if len(paired):
            out['brier_change_calibrated_minus_raw'] = out['calibrated']['brier'] - out['raw']['brier']
        out['same_raw_over80_group'] = {col: group_stats(paired[paired.p_home >= .8], col) for col in ['p_home', 'p_calibrated']}
        out['calibration_bins'] = {}
        for col in ['p_home', 'p_calibrated']:
            out['calibration_bins'][col] = []
            for lo, hi in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.000001)]:
                stats = group_stats(paired[(paired[col] >= lo) & (paired[col] < hi)], col)
                stats.update(lo=lo, hi=min(hi, 1))
                out['calibration_bins'][col].append(stats)
        return out
    current = now.year + int(now.month >= 10)
    report['base_version'] = base['version']
    report['source_games'] = base['source_games']
    report['by_recent_season'] = {str(year): evaluate(z[z.season == year]) for year in range(2024, current + 1)}
    recent = z[z.season == current].dropna(subset=['p_home'])
    tail = recent[recent.p_home >= .8]
    report['current_raw_over80'] = group_stats(tail, 'p_home')
    report['current_tail_by_team_history'] = {name: group_stats(g, 'p_home') for name, g in [('either_team_under10_prior_games', tail[(tail.prior_n_h < 10) | (tail.prior_n_a < 10)]), ('both_teams_at_least10_prior_games', tail[(tail.prior_n_h >= 10) & (tail.prior_n_a >= 10)])]}
    report['current_tail_case_references'] = [{'date': str(r.date.date()), 'game_id': r.game_id, 'home_team_id': r.team_id_h, 'away_team_id': r.team_id_a, 'raw_probability': float(r.p_home), 'candidate_probability': float(r.p_calibrated) if pd.notna(r.p_calibrated) else None, 'home_prior_games': int(r.prior_n_h), 'away_prior_games': int(r.prior_n_a)} for r in tail.itertuples()]
    report['neutral_site_handling'] = {'source_home_null_rows': base['missing_home_rows'], 'treatment': 'Rows remain usable in prior team histories; games without explicit home/away pairs are excluded as prediction targets. No invented home assignment. Neutral arenas otherwise not independently audited.'}
    training = z[(z.date >= pd.Timestamp(now.date()) - pd.DateOffset(years=3))].dropna(subset=['p_home'])
    if len(training) >= 500 and training.won.nunique() == 2:
        candidate = fit_cal(training)
        report['candidate_calibrator'] = {'deployed': False, 'input': 'logit(raw_home_win_probability), clipped to [0.000001, 0.999999]', 'coefficient': float(candidate.coef_[0, 0]), 'intercept': float(candidate.intercept_[0]), 'training_forward_predictions': len(training), 'latest_training_date': str(training.date.max().date())}
    report['execution_ok'] = True
except Exception as exc:
    report.update(error_type=type(exc).__name__, error=str(exc)[:6000], traceback=traceback.format_exc()[-10000:])
Path('reports/calibration_audit.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
print(json.dumps(report, indent=2, allow_nan=False))
