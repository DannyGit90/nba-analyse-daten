"""Bounded live minutes/seconds diagnostic; never a model approval."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
from playing_time_checks import compare_rows
from playing_time_fetch import fetch_exact

SOURCE = 'https://basketball-data.billmill.org/nba/nba.duckdb'


def inspect(con, now, limit=10):
    if now.tzinfo is None or now.utcoffset() is None or type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Aware time and sample limit 1..10 required')
    now = now.astimezone(dt.timezone.utc)
    season = now.year + int(now.month >= 10)
    cursor = con.execute("SELECT season,game_id,player_id,team_id,max(game_date) AS sample_date FROM nba.main.player_game_logs WHERE season=? AND game_id LIKE '002%' AND game_date<? GROUP BY season,game_id,player_id,team_id ORDER BY sample_date DESC,game_id,player_id,team_id LIMIT ?", [season, now.date(), limit])
    names = [column[0] for column in cursor.description]
    selected = [dict(zip(names, row)) for row in cursor.fetchall()]
    if not selected:
        raise ValueError('No eligible sample keys; no comparison claimed')
    keys = [{k: row[k] for k in ('season','game_id','player_id','team_id')} for row in selected]
    logs = fetch_exact(con, 'player_game_logs', keys)
    boxes = fetch_exact(con, 'player_box', keys)
    result = compare_rows(logs, boxes)
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()
    return {
        'season_end_year': season,
        'cutoff_utc_date_exclusive': now.date().isoformat(),
        'sample_key_limit': limit,
        'selected_keys': selected,
        'log_rows_sha256': digest(logs),
        'box_rows_sha256': digest(boxes),
        'log_rows_repr': [{k: repr(v) for k,v in row.items()} for row in logs],
        'box_rows_repr': [{k: repr(v) for k,v in row.items()} for row in boxes],
        'comparison': result,
    }


def probe(now, connector=None):
    report = {
        'schema': 'playing-time-live-probe-v1',
        'checked_at_utc': now.isoformat(), 'source': SOURCE,
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'tested_commit_sha': os.environ.get('GITHUB_SHA'),
        'read_only': True, 'execution_ok': False,
        'comparison_executed': False, 'source_read_attempted': False,
        'units_verified': False, 'model_input_approved': False,
        'production_model_changed': False, 'betting_release': False,
        'limitations': [
            'At most ten recent regular-season player-log keys; not a full-table audit or random sample.',
            'Keys are grouped only for selection; fetches preserve all source duplicates within resource bounds.',
            'Dates before the current UTC day do not prove game completion, freshness or historical availability.',
            'The source may change during reads; row hashes identify the returned data, not an immutable source snapshot.',
            'Source URL and sample dates are not independent identity, roster, unit or publication verification.',
            'Execution success means the comparison ran, not that values agree or are approved.',
        ],
    }
    con = None
    try:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('Aware audit time required')
        if connector is None:
            import duckdb
            connector = duckdb.connect
        con = connector()
        report['source_read_attempted'] = True
        con.execute("ATTACH '" + SOURCE + "' AS nba (READ_ONLY)")
        con.execute('BEGIN TRANSACTION')
        report.update(inspect(con, now))
        con.execute('COMMIT')
        report['execution_ok'] = True
        report['comparison_executed'] = True
    except Exception as exc:
        report['error'] = (type(exc).__name__ + ': ' + str(exc))[:1000]
    finally:
        if con is not None:
            con.close()
    return report


def main():
    report = probe(dt.datetime.now(dt.timezone.utc))
    try:
        report['actual_commit_sha'] = subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
        report['commit_matches_event'] = report['actual_commit_sha'] == report['tested_commit_sha']
    except Exception:
        report['commit_matches_event'] = False
    root = Path('probe-results')
    root.mkdir(exist_ok=True)
    (root / 'result.json').write_text(json.dumps(report, default=str, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(report, default=str, indent=2, allow_nan=False))
    return 0 if report['execution_ok'] and report['commit_matches_event'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
