"""Run playing-time regressions and write source-bound CI evidence."""
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import unittest
from collections import Counter


def main():
    out = Path('ci-results')
    out.mkdir(exist_ok=True)
    stream = io.StringIO()
    counts = Counter()
    result = None
    actual_sha = None
    error = None
    try:
        actual_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        sys.path.insert(0, str(Path('scripts').resolve()))
        suite = unittest.defaultTestLoader.discover('scripts', pattern='test_playing_time*.py')
        def count_tests(node):
            if isinstance(node, unittest.TestSuite):
                for child in node:
                    count_tests(child)
            else:
                counts[node.__class__.__module__] += 1
        count_tests(suite)
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    except Exception:
        error = traceback.format_exc()
        stream.write(error)
    prerequisites = {
        'dependencies_installed': os.environ.get('DEPENDENCY_OUTCOME') == 'success',
        'tested_commit_matches_event': bool(actual_sha) and actual_sha == os.environ.get('GITHUB_SHA'),
        'original_suite_present': counts['test_playing_time_checks'] >= 16,
        'integration_suite_present': counts['test_playing_time_fetch'] >= 8,
    }
    ok = bool(result is not None and result.wasSuccessful() and not result.skipped
              and all(prerequisites.values()) and error is None)
    report = {
        'schema': 'playing-time-ci-v1',
        'generated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'repository': os.environ.get('GITHUB_REPOSITORY'),
        'event': os.environ.get('GITHUB_EVENT_NAME'),
        'event_sha': os.environ.get('GITHUB_SHA'),
        'tested_commit_sha': actual_sha,
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'status': 'passed' if ok else 'failed',
        'prerequisites': prerequisites,
        'tests_by_module': dict(counts),
        'tests_run': result.testsRun if result is not None else 0,
        'failures': len(result.failures) if result is not None else None,
        'errors': len(result.errors) if result is not None else None,
        'skipped': len(result.skipped) if result is not None else None,
        'runner_error': error,
        'live_nba_query_executed': False,
        'model_input_approved': False,
        'betting_release': False,
    }
    log = stream.getvalue()
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (out / 'tests.txt').write_text(log, encoding='utf-8')
    print(log, end='')
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
