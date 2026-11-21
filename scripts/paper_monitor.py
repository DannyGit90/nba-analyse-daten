import datetime as dt
import json
import traceback
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline

PROTOCOL = 'season-prior10-paper-v1'
K = 10
ALPHA = 100.0
now = dt.datetime.now(dt.timezone.utc)
current = now.year + int(now.month >= 10)
Path('reports').mkdir(exist_ok=True)
Path('paper_log').mkdir(exist_ok=True)
report = {'protocol': PROTOCOL, 'generated_at_utc': now.isoformat(), 'execution_ok': False, 'status': 'paper_only_no_betting_release', 'money_betting_released': False, 'production_model_changed': False, 'forecasts': [], 'limitations': ['No quantified injury adjustment, no bookmaker-price or profitability validation.', 'Forecasts and aggregate evaluation are public; no private user or betting data.', 'Same UTC-day results are conservatively excluded; data may lag completed games.', 'Unknown game status or neutral venue blocks that game.', 'Monthly training matches tested protocol; features update from earlier completed dates.', 'First archived forecast per game is the predeclared evaluation choice. No outcome-based selection.', 'No minimum sample or result here automatically releases betting.', 'Residual empirical probabilities are experimental and not guaranteed calibrated.']}
try:
    audit = json.loads(Path('reports/season_prior_test.json').read_text())
    if not audit.get('execution_ok') or audit.get('selected_prior_strength') != K:
        raise ValueError('Frozen prior strength is not supported by the stored audit')
    from paper_data_refresh import load_checked
    (data, schedule, teams), refresh = load_checked(current, now)
    report['data_refresh'] = refresh
    abbreviations = {str(t): a for t, a in teams}
    for col in ['game_id', 'team_id', 'opp_team_id']:
        data[col] = data[col].astype(str)
    data['game_date'] = pd.to_datetime(data.game_date).dt.normalize()
    data = data[data.game_date < pd.Timestamp(now.date())].sort_values(['season', 'team_id', 'game_date', 'game_id']).copy()
    if data.duplicated(['season', 'team_id', 'game_date']).any() or data.duplicated(['season', 'game_id', 'team_id']).any():
        raise ValueError('Ambiguous team/date or duplicate game/team data')
    features = ['rest', 'prior_n']
    keys = ['season', 'team_id']
    data['prior_n'] = data.groupby(keys).cumcount()
    data['rest'] = (data.game_date - data.groupby(keys).game_date.shift()).dt.days.sub(1).clip(0, 7)
    ratings = ['off_rating', 'def_rating', 'pace']
    for col in ratings:
        data[col] = pd.to_numeric(data[col], errors='coerce').replace([np.inf, -np.inf], np.nan)
        data.loc[data[col] <= 0, col] = np.nan
        if data[col].isna().any():
            raise ValueError('Missing rating requires review before paper scoring: ' + col)
        data[col + '_season'] = data.groupby(keys)[col].transform(lambda s: s.shift().expanding(min_periods=1).mean())
        data[col + '_last10'] = data.groupby(keys)[col].transform(lambda s: s.shift().rolling(10, min_periods=1).mean())
        features.extend([col + '_season', col + '_last10'])
    prior = data.groupby(keys)[ratings].mean().reset_index()
    prior['season'] += 1
    prior = prior.rename(columns={c: c + '_prior' for c in ratings})
    bounds = data.groupby('season').game_date.agg(['min', 'max'])
    for year in bounds.index:
        if year - 1 in bounds.index and not bounds.loc[year - 1, 'max'] < bounds.loc[year, 'min']:
            raise ValueError('Overlapping seasons prevent safe previous-season prior')
    data = data.merge(prior, on=keys, how='left', validate='many_to_one')
    for col in ratings:
        mean = data[col + '_season']
        data[col + '_season'] = (data.prior_n * mean + K * data[col + '_prior'].fillna(mean)) / (data.prior_n + K)
    home = data[data.home.eq(True).fillna(False)]
    away = data[data.home.eq(False).fillna(False)]
    games = home.merge(away, on=['season', 'game_id', 'game_date'], suffixes=('_h', '_a'), validate='one_to_one')
    games = games[(games.prior_n_h >= 3) & (games.prior_n_a >= 3) & (games.team_id_h == games.opp_team_id_a) & (games.team_id_a == games.opp_team_id_h)].sort_values(['game_date', 'game_id']).reset_index(drop=True)
    names = [f + side for side in ['_h', '_a'] for f in features]
    X = games[names].to_numpy(dtype=float)
    Y = np.column_stack([games.pts_h - games.pts_a, games.pts_h + games.pts_a]).astype(float)
    def fit(ids):
        if len(ids) < 500:
            raise ValueError('Insufficient training games')
        return make_pipeline(SimpleImputer(strategy='median', keep_empty_features=True), StandardScaler(), Ridge(alpha=ALPHA)).fit(X[ids], Y[ids])
    cutoff = pd.Timestamp(now.date()) - pd.Timedelta(days=365)
    residuals = []
    periods = games.game_date.dt.to_period('M')
    for month in sorted(periods.unique()):
        ids = np.flatnonzero(((periods == month) & (games.game_date >= cutoff)).to_numpy())
        if not len(ids):
            continue
        year = int(games.iloc[ids[0]].season)
        tr = np.flatnonzero(((games.game_date < month.start_time) & (games.season >= year - 3)).to_numpy())
        model = fit(tr)
        residuals.extend((Y[ids] - model.predict(X[ids])).tolist())
    residuals = np.asarray(residuals, dtype=float)
    if len(residuals) < 200:
        raise ValueError('Insufficient historical forward errors')
    month_start = pd.Timestamp(now.date()).to_period('M').start_time
    tr = np.flatnonzero(((games.game_date < month_start) & (games.season >= current - 3)).to_numpy())
    model = fit(tr)
    report.update(training_games=len(tr), training_latest_game=str(games.iloc[tr].game_date.max().date()), feature_data_latest_game=str(data.game_date.max().date()), residual_n=len(residuals), prior_strength=K, ridge_alpha=ALPHA)
    schedule['start_time'] = pd.to_datetime(schedule.start_time, utc=True)
    schedule['game_date'] = pd.to_datetime(schedule.game_date).dt.normalize()
    upcoming = schedule[(schedule.start_time > pd.Timestamp(now)) & (schedule.start_time <= pd.Timestamp(now) + pd.Timedelta(hours=24))].sort_values('start_time')
    missing_finals = list(refresh['unresolved_game_ids'])
    report['completed_schedule_games_missing_from_logs'] = missing_finals
    report['skipped_games'] = []
    scheduled_values = {'1', 'scheduled', 'pre', 'pregame', 'not started', 'pre-game'}
    def future_features(team, date):
        z = data[(data.season == current) & (data.team_id == team) & (data.game_date < date)].sort_values(['game_date', 'game_id'])
        if len(z) < 3:
            raise ValueError('Fewer than three earlier season games')
        old = prior[(prior.season == current) & (prior.team_id == team)]
        if len(old) != 1:
            raise ValueError('Missing or ambiguous previous-season prior')
        values = {'rest': min(7, max(0, (date - z.game_date.max()).days - 1)), 'prior_n': len(z)}
        for col in ratings:
            values[col + '_season'] = (len(z) * z[col].mean() + K * float(old.iloc[0][col + '_prior'])) / (len(z) + K)
            values[col + '_last10'] = z.tail(10)[col].mean()
        return [values[f] for f in features]
    for g in upcoming.itertuples():
        try:
            if missing_finals:
                raise ValueError('Completed schedule games missing from loaded logs; freshness check failed')
            if pd.isna(g.neutral_site) or bool(g.neutral_site):
                raise ValueError('Neutral or unknown venue')
            if str(g.status).strip().lower() not in scheduled_values:
                raise ValueError('Unrecognized or non-pregame status: ' + str(g.status))
            h, a = str(g.home_team_id), str(g.away_team_id)
            if h not in abbreviations or a not in abbreviations:
                raise ValueError('NBA team mapping unavailable')
            earlier = schedule[(schedule.start_time > pd.Timestamp(now)) & (schedule.start_time < g.start_time)]
            if earlier.home_team_id.astype(str).isin([h, a]).any() or earlier.away_team_id.astype(str).isin([h, a]).any():
                raise ValueError('Intervening unplayed team game before this fixture')
            x = np.array(future_features(h, g.game_date) + future_features(a, g.game_date), dtype=float).reshape(1, -1)
            margin, total = model.predict(x)[0]
            ph = float(np.mean(margin + residuals[:, 0] > 0))
            mi = (margin + np.quantile(residuals[:, 0], [.1, .9])).tolist()
            ti = (total + np.quantile(residuals[:, 1], [.1, .9])).tolist()
            report['forecasts'].append({'game_id': str(g.game_id), 'start_time_utc': g.start_time.isoformat(), 'home_team_id': h, 'away_team_id': a, 'home': abbreviations[h], 'away': abbreviations[a], 'p_home_experimental': ph, 'p_away_experimental': 1 - ph, 'home_margin_point': float(margin), 'total_point': float(total), 'margin_interval80': mi, 'total_interval80': ti, 'baseline_home_probability': float(np.mean(Y[tr, 0] > 0)), 'betting_release': False})
        except Exception as exc:
            report['skipped_games'].append({'game_id': str(g.game_id), 'reason': str(exc)})
    report['upcoming_schedule_games'] = len(upcoming)
    report['execution_ok'] = True
    archive = Path('paper_log') / (now.strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    archive.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    first = {}
    for path in sorted(Path('paper_log').glob('*.json')):
        snapshot = json.loads(path.read_text())
        if snapshot.get('protocol') != PROTOCOL or not snapshot.get('execution_ok'):
            continue
        for f in snapshot.get('forecasts', []):
            if pd.Timestamp(snapshot['generated_at_utc']) < pd.Timestamp(f['start_time_utc']):
                first.setdefault(f['game_id'], f)
    actual = {str(g.game_id): g for g in games.itertuples()}
    scored = []
    for gid, f in first.items():
        if gid not in actual:
            continue
        g = actual[gid]
        if str(g.team_id_h) != f['home_team_id'] or str(g.team_id_a) != f['away_team_id']:
            continue
        won = int(g.pts_h > g.pts_a)
        scored.append({'model_brier': (f['p_home_experimental'] - won) ** 2, 'baseline_brier': (f['baseline_home_probability'] - won) ** 2, 'margin_abs_error': abs(f['home_margin_point'] - (g.pts_h - g.pts_a)), 'total_abs_error': abs(f['total_point'] - (g.pts_h + g.pts_a))})
    evaluation = {'protocol': PROTOCOL, 'checked_at_utc': now.isoformat(), 'status': 'prospective_paper_only', 'betting_release': False, 'unique_games_archived': len(first), 'games_scored': len(scored), 'selection_rule': 'Earliest stored pregame forecast per game; no retrospective forecasts inserted.'}
    if scored:
        evaluation['metrics'] = {k: float(np.mean([r[k] for r in scored])) for k in scored[0]}
    Path('reports/paper_evaluation.json').write_text(json.dumps(evaluation, indent=2, allow_nan=False) + '\n')
except Exception as exc:
    report.update(error_type=type(exc).__name__, error=str(exc)[:6000], traceback=traceback.format_exc()[-10000:])
Path('reports/paper_latest.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
print(json.dumps(report, indent=2, allow_nan=False))
