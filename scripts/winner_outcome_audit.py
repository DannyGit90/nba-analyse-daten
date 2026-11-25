"""Read-only winner/result matching; no calibration, EV or betting release.

Supplied final status is not a historical publication-time proof.
"""
import argparse
import datetime as dt
import json
import math
from pathlib import Path
from winner_snapshot_audit import audit, timestamp


def group(rows):
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('game_id'), str):
            raise ValueError('Source rows require string game_id')
        result.setdefault(row['game_id'], []).append(row)
    return result


def points(value):
    if type(value) not in (int, float):
        raise ValueError('Invalid points')
    try:
        if not math.isfinite(value) or value < 0 or value != int(value):
            raise ValueError('Invalid points')
    except OverflowError as exc:
        raise ValueError('Invalid points') from exc
    return int(value)


def match(snapshot, logs, schedule, as_of):
    formal = audit(snapshot)
    now = timestamp(as_of)
    results, fixtures = group(logs), group(schedule)
    rows = []
    forecasts = snapshot.get('forecasts')
    forecasts = forecasts if isinstance(forecasts, list) else []
    for forecast, checked in zip(forecasts, formal['forecasts']):
        row = {'game_id': checked['game_id'], 'status': 'unresolved'}
        try:
            if checked['status'] != 'formal_consistent':
                raise ValueError('Formal audit failed: ' + ', '.join(checked['errors']))
            gid = forecast['game_id']
            candidates = fixtures.get(gid, [])
            if len(candidates) != 1:
                raise ValueError('Missing or duplicate schedule row')
            fixture = candidates[0]
            if any(fixture.get(k) != forecast[k] for k in ('home_team_id', 'away_team_id')):
                raise ValueError('Schedule team identity mismatch')
            start = timestamp(fixture.get('start_time'))
            if start != timestamp(forecast['start_time_utc']):
                raise ValueError('Scheduled start differs from archived forecast')
            if start >= now or fixture.get('status') != 'final':
                raise ValueError('Game not confirmed final as of check')
            pair = results.get(gid, [])
            home = [r for r in pair if r.get('team_id') == forecast['home_team_id']
                    and r.get('opp_team_id') == forecast['away_team_id'] and r.get('home') is True]
            away = [r for r in pair if r.get('team_id') == forecast['away_team_id']
                    and r.get('opp_team_id') == forecast['home_team_id'] and r.get('home') is False]
            if len(pair) != 2 or len(home) != 1 or len(away) != 1:
                raise ValueError('Missing, duplicate or mismatched result pair')
            date = fixture.get('game_date')
            if not isinstance(date, str) or any(r.get('game_date') != date for r in pair):
                raise ValueError('Result date does not match schedule')
            dt.date.fromisoformat(date)
            h, a = points(home[0].get('pts')), points(away[0].get('pts'))
            if h == a:
                raise ValueError('Tied final is not a two-way winner result')
            winner = 'home' if h > a else 'away'
            row.update(status='matched', home_points=h, away_points=a, winner=winner,
                       winner_team_id=forecast[winner + '_team_id'])
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            row['reason'] = str(exc)
        rows.append(row)
    matched = sum(r['status'] == 'matched' for r in rows)
    status = ('invalid_snapshot' if formal['errors'] else 'no_forecasts' if not rows
              else 'matched' if matched == len(rows) else 'partial' if matched else 'unresolved')
    return {'schema': 'winner-outcome-audit-v1', 'status': status, 'as_of_utc': now.astimezone(dt.timezone.utc).isoformat(),
            'source_scope': 'supplied_schedule_and_team_logs', 'formal_errors': formal['errors'],
            'forecast_count': len(rows), 'matched_count': matched, 'forecasts': rows,
            'historical_publication_verified': False,
            'probability_validation': 'not_assessed', 'betting_release': False}


def selected(path, ids):
    rows = []
    with path.open(encoding='utf-8') as source:
        for line in source:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('JSONL objects required')
                if row.get('game_id') in ids:
                    rows.append(row)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--data-root', type=Path, default=Path('data/nba'))
    parser.add_argument('--as-of', default=dt.datetime.now(dt.timezone.utc).isoformat())
    args = parser.parse_args(argv)
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
        formal = audit(snapshot)
        logs, schedule, files = [], [], []
        forecasts = snapshot.get('forecasts')
        valid = [f for f, r in zip(forecasts if isinstance(forecasts, list) else [], formal['forecasts'])
                 if r['status'] == 'formal_consistent']
        if valid:
            ids = {f['game_id'] for f in valid}
            starts = [timestamp(f['start_time_utc']).astimezone(dt.timezone.utc) for f in valid]
            seasons = {t.year + int(t.month >= 10) for t in starts}
            for season in sorted(seasons):
                for folder, target in [('team_game_logs', logs), ('schedule', schedule)]:
                    path = args.data_root / folder / ('season=' + str(season) + '.jsonl')
                    target.extend(selected(path, ids))
                    files.append(str(path))
        result = match(snapshot, logs, schedule, args.as_of)
        result['source_files'] = files
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        result = {'schema': 'winner-outcome-audit-v1', 'status': 'source_error',
                  'reason': str(exc), 'probability_validation': 'not_assessed', 'betting_release': False}
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
