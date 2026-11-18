import argparse
import datetime as dt
import json
from pathlib import Path


def assess(p, e, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    r = {'checked_at_utc': now.isoformat(), 'source_generated_at_utc': p.get('generated_at_utc'),
         'status': 'invalid_report', 'pipeline_usable': False, 'betting_release': False,
         'max_report_age_hours': 8}
    try:
        stamp = dt.datetime.fromisoformat(p['generated_at_utc'])
        evaluated = dt.datetime.fromisoformat(e['checked_at_utc'])
        if stamp.tzinfo is None or evaluated.tzinfo is None or not stamp <= evaluated <= now:
            raise ValueError('Invalid or inconsistent report times')
        if not p.get('protocol') or p['protocol'] != e.get('protocol'):
            raise ValueError('Missing or mismatched protocols')
        if p.get('execution_ok') is not True or e.get('execution_ok') is not True:
            r['status'] = 'execution_error'
            return r
        if p.get('money_betting_released') is not False or e.get('betting_release') is not False:
            raise ValueError('Unexpected release state')
        f, s, missing = p['forecasts'], p['skipped_games'], p['completed_schedule_games_missing_from_logs']
        n = p['upcoming_schedule_games']
        if not all(isinstance(x, list) for x in [f, s, missing]) or type(n) is not int or n < 0:
            raise ValueError('Invalid coverage fields')
        ids = [x['game_id'] for x in f + s]
        if any(not isinstance(x, str) or not x for x in ids + missing):
            raise ValueError('Invalid game ID')
        if len(ids) != n or len(set(ids)) != len(ids):
            raise ValueError('Duplicate or unaccounted-for fixture IDs')
        r.update(upcoming_games=n, forecast_games=len(f), skipped_games=len(s),
                 missing_completed_game_ids=missing)
        if missing:
            r['status'] = 'blocked_freshness'
        elif now - stamp > dt.timedelta(hours=8):
            r['status'] = 'stale_report'
        elif n == 0:
            r.update(status='no_upcoming_games', pipeline_usable=True)
        elif not f:
            r['status'] = 'blocked_no_forecasts'
        else:
            r.update(status='partial' if s else 'ready_paper_only', pipeline_usable=True)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        r.update(status='invalid_report', pipeline_usable=False, error=str(exc))
    return r


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        p = json.loads(Path('reports/paper_latest.json').read_text())
        e = json.loads(Path('reports/paper_evaluation.json').read_text())
        if not isinstance(p, dict) or not isinstance(e, dict):
            raise ValueError('Report roots must be objects')
        r = assess(p, e)
    except (OSError, ValueError) as exc:
        r = {'status': 'invalid_report', 'pipeline_usable': False,
             'betting_release': False, 'error': str(exc)}
    text = json.dumps(r, indent=2, allow_nan=False) + '\n'
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    print(text, end='')
    return int(args.check and not r['pipeline_usable'])


if __name__ == '__main__':
    raise SystemExit(main())
