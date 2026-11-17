import datetime as dt
import json
import traceback
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline

VERSION = 'NBA-Ridge-GH-1'
ALPHA = 100.0
now = dt.datetime.now(dt.timezone.utc)
current = now.year + int(now.month >= 10)
Path('reports').mkdir(exist_ok=True)
report = {'version': VERSION, 'created_at_utc': now.isoformat(), 'execution_ok': False, 'status': 'experimental_no_betting_release', 'alpha_fixed_before_run': ALPHA, 'parameter_search': False, 'primary_evaluation_season': 2026, 'method': 'Monthly expanding-within-season walk-forward; prior three seasons plus elapsed current season; minimum 500 training games. Empirical errors from preceding 365 days, minimum 200. No odds features.', 'limitations': ['No independently verified schedule completeness.', 'No opponent-adjusted ratings or quantified injury adjustments.', 'Neutral venues are not separately identified.', 'No historical price/profitability or spread/total probability calibration test.', 'End scores include overtime; no separate overtime model.', 'Three-game minimum omits early-season games.', 'Historical results are not prospective evidence of profitability.'], 'money_betting_released': False}
try:
    con = duckdb.connect()
    con.execute("ATTACH 'https://basketball-data.billmill.org/nba/nba.duckdb' AS nba")
    data = con.execute("SELECT season, game_id, team_id, opp_team_id, game_date, home, pts, off_rating, def_rating, pace FROM nba.team_game_logs WHERE season BETWEEN 2010 AND ? AND CAST(game_id AS VARCHAR) LIKE '002%'", [current]).df()
    con.close()
    for col in ['game_id', 'team_id', 'opp_team_id']:
        data[col] = data[col].astype(str)
    data['game_date'] = pd.to_datetime(data.game_date).dt.normalize()
    data = data[data.game_date < pd.Timestamp(now.date())].copy()
    if data.duplicated(['season', 'game_id', 'team_id']).any():
        raise ValueError('Duplicate game/team keys')
    if data.duplicated(['season', 'team_id', 'game_date']).any():
        raise ValueError('Multiple team games on one date: daily feature isolation needs review')
    data = data.sort_values(['season', 'team_id', 'game_date', 'game_id'])
    keys = ['season', 'team_id']
    data['prior_n'] = data.groupby(keys).cumcount()
    data['rest'] = (data.game_date - data.groupby(keys).game_date.shift(1)).dt.days.sub(1).clip(0, 7)
    features = ['rest', 'prior_n']
    report['missing_input_ratings'] = {}
    for col in ['off_rating', 'def_rating', 'pace']:
        data[col] = pd.to_numeric(data[col], errors='coerce').replace([np.inf, -np.inf], np.nan)
        data.loc[data[col] <= 0, col] = np.nan
        report['missing_input_ratings'][col] = int(data[col].isna().sum())
        for name, window in [('season', None), ('last10', 10)]:
            target = col + '_' + name
            if window is None:
                data[target] = data.groupby(keys)[col].transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
            else:
                data[target] = data.groupby(keys)[col].transform(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
            features.append(target)
    home = data[data.home.eq(True).fillna(False)].copy()
    away = data[data.home.eq(False).fillna(False)].copy()
    games = home.merge(away, on=['season', 'game_id', 'game_date'], suffixes=('_h', '_a'), validate='one_to_one')
    games = games[(games.team_id_h == games.opp_team_id_a) & (games.team_id_a == games.opp_team_id_h)].copy()
    report['source_games'] = int(data.groupby(['season', 'game_id']).ngroups)
    report['missing_home_rows'] = int(data.home.isna().sum())
    report['games_with_home_away_pair'] = len(games)
    games = games[(games.prior_n_h >= 3) & (games.prior_n_a >= 3)].sort_values(['game_date', 'game_id']).reset_index(drop=True)
    if games[['pts_h', 'pts_a']].isna().any().any():
        raise ValueError('Missing outcome points')
    games['margin'] = games.pts_h - games.pts_a
    games['total'] = games.pts_h + games.pts_a
    names = [f + side for side in ['_h', '_a'] for f in features]
    X = games[names].to_numpy(dtype=float)
    Y = games[['margin', 'total']].to_numpy(dtype=float)
    records = []
    def fit(x, y):
        return make_pipeline(SimpleImputer(strategy='median', keep_empty_features=True), StandardScaler(), Ridge(alpha=ALPHA)).fit(x, y)
    for period in sorted(games.game_date.dt.to_period('M').unique()):
        start = period.start_time
        test_ids = np.flatnonzero((games.game_date.dt.to_period('M') == period).to_numpy())
        season = int(games.iloc[test_ids[0]].season)
        train_ids = np.flatnonzero(((games.game_date < start) & (games.season >= season - 3)).to_numpy())
        if len(train_ids) < 500:
            continue
        assert games.iloc[train_ids].game_date.max() < games.iloc[test_ids].game_date.min()
        model = fit(X[train_ids], Y[train_ids])
        pred = model.predict(X[test_ids])
        base = Y[train_ids].mean(axis=0)
        old = [r for r in records if pd.Timestamp(r['date']) < start and pd.Timestamp(r['date']) >= start - pd.Timedelta(days=365)]
        if len(old) >= 200:
            em = np.array([r['actual_margin'] - r['pred_margin'] for r in old])
            et = np.array([r['actual_total'] - r['pred_total'] for r in old])
            eb = np.array([r['actual_margin'] - r['base_margin'] for r in old])
        for j, idx in enumerate(test_ids):
            g = games.iloc[idx]
            row = {'date': str(g.game_date.date()), 'season': int(g.season), 'actual_margin': float(Y[idx, 0]), 'actual_total': float(Y[idx, 1]), 'pred_margin': float(pred[j, 0]), 'pred_total': float(pred[j, 1]), 'base_margin': float(base[0]), 'base_total': float(base[1]), 'n_train': len(train_ids), 'residual_n': len(old)}
            if len(old) >= 200:
                row['p_home'] = float(np.mean(pred[j, 0] + em > 0))
                row['p_base'] = float(np.mean(base[0] + eb > 0))
                for target, errors, center in [('margin', em, pred[j, 0]), ('total', et, pred[j, 1])]:
                    for level, q in [('80', [.1, .9]), ('95', [.025, .975])]:
                        lo, hi = center + np.quantile(errors, q)
                        row[target + '_covered' + level] = bool(lo <= row['actual_' + target] <= hi)
            records.append(row)
    oos = pd.DataFrame(records)
    if oos.empty or 'p_home' not in oos:
        raise ValueError('Insufficient forward predictions for probability testing')
    def metrics(z):
        result = {'games': len(z), 'first_date': z.date.min(), 'last_date': z.date.max()}
        for target in ['margin', 'total']:
            for method in ['pred', 'base']:
                error = z['actual_' + target] - z[method + '_' + target]
                result[target + '_' + method + '_mae'] = float(np.abs(error).mean())
                result[target + '_' + method + '_rmse'] = float(np.sqrt(np.mean(error ** 2)))
            for level in ['80', '95']:
                covered = z[target + '_covered' + level].dropna()
                result[target + '_coverage' + level] = float(covered.mean()) if len(covered) else None
        pz = z.dropna(subset=['p_home', 'p_base'])
        result['probability_games'] = len(pz)
        if len(pz):
            wins = (pz.actual_margin > 0).astype(float)
            result['brier_model'] = float(np.mean((pz.p_home - wins) ** 2))
            result['brier_base'] = float(np.mean((pz.p_base - wins) ** 2))
            bins = []
            for lo, hi in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.000001)]:
                b = pz[(pz.p_home >= lo) & (pz.p_home < hi)]
                bins.append({'lo': lo, 'hi': min(hi, 1), 'n': len(b), 'mean_p': float(b.p_home.mean()) if len(b) else None, 'win_rate': float((b.actual_margin > 0).mean()) if len(b) else None})
            result['calibration_bins'] = bins
        return result
    report['eligible_games'] = len(games)
    report['forward_predictions'] = len(oos)
    report['overall'] = metrics(oos)
    report['by_season'] = {str(int(season)): metrics(z) for season, z in oos.groupby('season')}
    report['primary_evaluation'] = report['by_season'].get('2026')
    ids = np.flatnonzero((games.season >= current - 3).to_numpy())
    final = fit(X[ids], Y[ids])
    imp, scale, ridge = final.steps[0][1], final.steps[1][1], final.steps[2][1]
    cutoff = pd.Timestamp(now.date()) - pd.Timedelta(days=365)
    recent = oos[pd.to_datetime(oos.date) >= cutoff]
    state = {'version': VERSION, 'created_at_utc': now.isoformat(), 'status': 'experimental_no_betting_release', 'feature_names': names, 'training_games': len(ids), 'training_latest_game': str(games.iloc[ids].game_date.max().date()), 'imputer_statistics': imp.statistics_.tolist(), 'scaler_mean': scale.mean_.tolist(), 'scaler_scale': scale.scale_.tolist(), 'ridge_coef': ridge.coef_.tolist(), 'ridge_intercept': ridge.intercept_.tolist(), 'target_order': ['home_margin', 'total'], 'margin_residuals': (recent.actual_margin - recent.pred_margin).tolist(), 'total_residuals': (recent.actual_total - recent.pred_total).tolist(), 'residual_window_days': 365, 'note': 'Derived model state only. Not a daily forecast. No price or injury adjustment.'}
    Path('reports/model_state.json').write_text(json.dumps(state, indent=2, allow_nan=False) + '\n')
    report['execution_ok'] = True
except Exception as exc:
    report.update(error_type=type(exc).__name__, error=str(exc)[:6000], traceback=traceback.format_exc()[-10000:])
Path('reports/model_test.json').write_text(json.dumps(report, indent=2, default=str, allow_nan=False) + '\n')
print(json.dumps(report, indent=2, default=str, allow_nan=False))
