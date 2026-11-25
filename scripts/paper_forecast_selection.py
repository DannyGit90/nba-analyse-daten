"""Read-only selection of the earliest formally valid pregame forecast per game.

No results, calibration, EV or betting release. Selection never uses outcomes.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
from winner_snapshot_audit import audit, timestamp

RULE = ('Earliest formally valid forecast by generated_at_utc per game and supported protocol; '
        'conflicting identities or simultaneous differing forecasts are not selected.')


def utc(value):
    return timestamp(value).astimezone(dt.timezone.utc)


def identity(forecast):
    return (forecast['home_team_id'], forecast['away_team_id'], utc(forecast['start_time_utc']).isoformat())


def collect(root):
    candidates, invalid, unreadable, files = {}, {}, [], 0
    unnamed = 0
    for path in sorted((p for p in Path(root).iterdir() if p.suffix.lower() == '.json'), key=lambda p: p.name):
        files += 1
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError('regular_non_symlink_file_required')
            snapshot = json.loads(path.read_text(encoding='utf-8'))
            checked = audit(snapshot)
            generated = utc(snapshot['generated_at_utc']) if not checked['errors'] else None
            for forecast, row in zip(snapshot['forecasts'], checked['forecasts']):
                gid = row['game_id']
                if row['status'] == 'formal_consistent':
                    candidates.setdefault(gid, []).append(
                        {'path': str(path), 'generated': generated, 'forecast': forecast})
                elif gid is None:
                    unnamed += 1
                else:
                    invalid.setdefault(gid, set()).update(row['errors'])
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            unreadable.append({'path': str(path), 'error': type(exc).__name__ + ': ' + str(exc)[:300]})
    return candidates, invalid, unreadable, files, unnamed


def select(candidates, invalid):
    games = []
    for gid in sorted(set(candidates) | set(invalid)):
        items = sorted(candidates.get(gid, []), key=lambda c: (c['generated'], c['path']))
        row = {'game_id': gid, 'valid_candidate_count': len(items)}
        if not items:
            row.update(status='no_valid_forecast', errors=sorted(invalid.get(gid, [])))
        elif len({identity(c['forecast']) for c in items}) != 1:
            row.update(status='conflict', reason='game_identity_differs_between_snapshots')
        else:
            first = items[0]
            tied = [c for c in items if c['generated'] == first['generated']]
            if any(c['forecast'] != first['forecast'] for c in tied):
                row.update(status='conflict', reason='simultaneous_forecasts_differ')
            else:
                row.update(status='selected', source_path=first['path'],
                           generated_at_utc=first['generated'].isoformat(), forecast=first['forecast'])
        games.append(row)
    return games


def build(root):
    report = {'schema': 'paper-forecast-selection-v1', 'selection_rule': RULE, 'archive_root': str(root),
              'status': 'source_error', 'execution_ok': False, 'files_read': 0, 'unreadable_files': [],
              'games': [], 'selected_count': 0, 'conflict_count': 0, 'no_valid_forecast_count': 0,
              'forecasts_without_game_id': 0, 'errors': [], 'outcomes_used': False,
              'forecast_validation': 'not_assessed', 'betting_release': False}
    try:
        candidates, invalid, unreadable, files, unnamed = collect(root)
    except OSError as exc:
        report['errors'].append(type(exc).__name__ + ': ' + str(exc)[:300])
        return report
    games = select(candidates, invalid)
    count = lambda name: sum(g['status'] == name for g in games)
    report.update(execution_ok=True, files_read=files, unreadable_files=unreadable, games=games,
                  selected_count=count('selected'), conflict_count=count('conflict'),
                  no_valid_forecast_count=count('no_valid_forecast'), forecasts_without_game_id=unnamed)
    clean = not unreadable and not report['conflict_count']
    report['status'] = 'empty' if not files else 'complete' if clean else 'complete_with_issues'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive_root', type=Path, nargs='?', default=Path('paper_log'))
    result = build(parser.parse_args(argv).archive_root)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result['status'] in ('complete', 'empty') else 1


if __name__ == '__main__':
    raise SystemExit(main())
