"""Read one paper snapshot; check internal winner-probability consistency only.

No schedule verification, calibration, EV, recommendation or input-file writes.
"""
import argparse
from collections import Counter
import datetime as dt
import json
import math
from pathlib import Path
import re

PROTOCOL = 'season-prior10-paper-v1'


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('ISO timestamp string required')
    value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone required')
    return value


def probability(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and 0 <= value <= 1
    except OverflowError:
        return False


def audit(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError('Snapshot object required')
    errors = []
    if snapshot.get('protocol') != PROTOCOL:
        errors.append('unexpected_protocol')
    if snapshot.get('execution_ok') is not True:
        errors.append('source_execution_not_ok')
    generated = None
    try:
        generated = timestamp(snapshot.get('generated_at_utc'))
    except (ValueError, TypeError, OverflowError):
        errors.append('invalid_generated_timestamp')
    forecasts = snapshot.get('forecasts')
    if not isinstance(forecasts, list):
        errors.append('forecasts_not_a_list')
        forecasts = []
    counts = Counter(f.get('game_id') for f in forecasts
                     if isinstance(f, dict) and isinstance(f.get('game_id'), str))
    rows = []
    for forecast in forecasts:
        issues = list(errors)
        f = forecast if isinstance(forecast, dict) else {}
        if not isinstance(forecast, dict):
            issues.append('forecast_not_an_object')
        gid = f.get('game_id')
        if not isinstance(gid, str) or not re.fullmatch(r'002[0-9]{7}', gid):
            issues.append('invalid_game_id')
        elif counts[gid] != 1:
            issues.append('duplicate_game_id')
        for field in ('home_team_id', 'away_team_id'):
            if not isinstance(f.get(field), str) or not re.fullmatch(r'[0-9]{10}', f[field]):
                issues.append('invalid_' + field)
        if f.get('home_team_id') == f.get('away_team_id'):
            issues.append('identical_team_ids')
        for field in ('home', 'away'):
            if not isinstance(f.get(field), str) or not re.fullmatch(r'[A-Z]{2,4}', f[field]):
                issues.append('invalid_' + field + '_label')
        if f.get('home') == f.get('away'):
            issues.append('identical_team_labels')
        try:
            start = timestamp(f.get('start_time_utc'))
            if generated is not None and generated >= start:
                issues.append('not_generated_before_scheduled_start')
        except (ValueError, TypeError, OverflowError):
            issues.append('invalid_start_timestamp')
        home, away = f.get('p_home_experimental'), f.get('p_away_experimental')
        if not probability(home) or not probability(away):
            issues.append('invalid_winner_probability')
        elif not math.isclose(home + away, 1.0, rel_tol=0, abs_tol=1e-12):
            issues.append('winner_probabilities_do_not_sum_to_one')
        rows.append({'game_id': gid if isinstance(gid, str) else None,
                     'status': 'invalid' if issues else 'formal_consistent', 'errors': issues})
    consistent = sum(row['status'] == 'formal_consistent' for row in rows)
    status = ('invalid' if errors or consistent != len(rows)
              else 'formal_consistent' if rows else 'no_forecasts')
    return {'schema': 'winner-formal-audit-v1', 'protocol': PROTOCOL,
            'scope': 'internal_snapshot_only_no_schedule_verification',
            'status': status, 'errors': errors, 'forecast_count': len(rows),
            'consistent_count': consistent, 'forecasts': rows,
            'probability_validation': 'not_assessed', 'betting_release': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit(json.loads(args.snapshot.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        result = {'schema': 'winner-formal-audit-v1', 'status': 'invalid',
                  'errors': [str(exc)], 'probability_validation': 'not_assessed',
                  'betting_release': False}
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result['status'] == 'formal_consistent' else 2 if result['status'] == 'no_forecasts' else 1


if __name__ == '__main__':
    raise SystemExit(main())
