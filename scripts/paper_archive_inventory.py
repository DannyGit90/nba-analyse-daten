"""Read-only inventory of archive metadata, not forecast validation or selection."""
import argparse
import datetime as dt
import json
from pathlib import Path


def inspect_file(path):
    row = {'path': str(path), 'status': 'invalid', 'protocol': None,
           'generated_at_utc': None, 'forecast_count': None, 'errors': []}
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError('regular_non_symlink_file_required')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('snapshot_object_required')
        protocol = data.get('protocol')
        if isinstance(protocol, str) and protocol.strip():
            row['protocol'] = protocol
        else:
            row['errors'].append('invalid_protocol_label')
        stamp = data.get('generated_at_utc')
        try:
            if not isinstance(stamp, str):
                raise ValueError('timestamp_string_required')
            parsed = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError('timezone_required')
            row['generated_at_utc'] = parsed.astimezone(dt.timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError):
            row['errors'].append('invalid_generated_timestamp')
        forecasts = data.get('forecasts')
        if isinstance(forecasts, list):
            row['forecast_count'] = len(forecasts)
        else:
            row['errors'].append('forecasts_not_a_list')
        if not row['errors']:
            row['status'] = 'metadata_ok'
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        row['errors'].append(type(exc).__name__ + ': ' + str(exc)[:300])
    return row


def inventory(root):
    root = Path(root)
    report = {'schema': 'paper-archive-inventory-v1', 'scope': 'top_level_json_metadata_only',
              'archive_root': str(root), 'status': 'source_error', 'execution_ok': False,
              'files': [], 'file_count': 0, 'metadata_ok_count': 0, 'invalid_file_count': 0,
              'errors': [], 'forecast_validation': 'not_assessed', 'betting_release': False}
    try:
        paths = sorted((p for p in root.iterdir() if p.suffix.lower() == '.json'), key=lambda p: p.name)
    except OSError as exc:
        report['errors'].append(type(exc).__name__ + ': ' + str(exc)[:300])
        return report
    rows = [inspect_file(path) for path in paths]
    good = sum(row['status'] == 'metadata_ok' for row in rows)
    report.update(files=rows, file_count=len(rows), metadata_ok_count=good,
                  invalid_file_count=len(rows) - good, execution_ok=True,
                  status='empty' if not rows else 'complete' if good == len(rows) else 'complete_with_errors')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive_root', type=Path, nargs='?', default=Path('paper_log'))
    result = inventory(parser.parse_args(argv).archive_root)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result['execution_ok'] and not result['invalid_file_count'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
