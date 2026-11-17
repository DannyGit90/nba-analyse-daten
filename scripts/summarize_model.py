import datetime as dt
import json
from pathlib import Path
import duckdb

now = dt.datetime.now(dt.timezone.utc)
current = now.year + int(now.month >= 10)
r = json.loads(Path('reports/model_test.json').read_text())
s = json.loads(Path('reports/model_state.json').read_text())
summary = {'checked_at_utc': now.isoformat(), 'version': r['version'], 'model_execution_ok': r['execution_ok'], 'model_created_at_utc': r['created_at_utc'], 'status': r['status'], 'money_betting_released': False, 'source_games': r.get('source_games'), 'eligible_games': r.get('eligible_games'), 'forward_predictions': r.get('forward_predictions'), 'overall': r.get('overall'), 'primary_evaluation_season': r['primary_evaluation_season'], 'primary_evaluation': r.get('primary_evaluation'), 'recent_seasons': {str(y): r.get('by_season', {}).get(str(y)) for y in range(2024, current + 1)}, 'state': {'version': s['version'], 'training_games': s['training_games'], 'training_latest_game': s['training_latest_game'], 'feature_count': len(s['feature_names']), 'margin_residual_n': len(s['margin_residuals']), 'total_residual_n': len(s['total_residuals'])}, 'limitations': r['limitations'], 'schedule_probe': {'ok': False}, 'daily_forecasts_created': False, 'scheduled_updates_enabled': False}
try:
    con = duckdb.connect()
    con.execute("ATTACH 'https://basketball-data.billmill.org/nba/nba.duckdb' AS nba")
    for table in ['schedule', 'team_seasons']:
        info = con.execute('DESCRIBE SELECT * FROM nba.' + table).fetchall()
        summary['schedule_probe'][table + '_columns'] = [{'name': x[0], 'type': x[1]} for x in info]
        summary['schedule_probe'][table + '_rows_current_season'] = con.execute('SELECT count(*) FROM nba.' + table + ' WHERE season = ?', [current]).fetchone()[0]
    con.close()
    summary['schedule_probe']['ok'] = True
except Exception as exc:
    summary['schedule_probe'].update(error_type=type(exc).__name__, error=str(exc)[:3000])
Path('reports/model_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
print(json.dumps(summary, indent=2, allow_nan=False))
