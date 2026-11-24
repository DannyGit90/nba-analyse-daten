"""Local model inputs by default; explicit reference-loader tests remain supported."""
import datetime as dt
import math
import copy
import hashlib
import os
import re
from pathlib import Path

SOURCE = 'https://basketball-data.billmill.org/nba/nba.duckdb'
LOG_SQL = "SELECT season, game_id, team_id, opp_team_id, game_date, home, pts, off_rating, def_rating, pace FROM nba.team_game_logs WHERE season BETWEEN 2010 AND ? AND CAST(game_id AS VARCHAR) LIKE '002%'"
SCHEDULE_SQL = "SELECT game_id, game_date, start_time, home_team_id, away_team_id, neutral_site, status FROM nba.schedule WHERE season = ? AND CAST(game_id AS VARCHAR) LIKE '002%'"


def fetch_snapshot(season):
    """Explicit online reference only; not used by the standard model path."""
    import duckdb
    con = duckdb.connect()
    try:
        con.execute("ATTACH '" + SOURCE + "' AS nba")
        data = con.execute(LOG_SQL, [season]).df()
        schedule = con.execute(SCHEDULE_SQL, [season]).df()
        teams = con.execute('SELECT team_id, nba_abbrev FROM nba.team_seasons WHERE season = ? AND is_nba = true', [season]).fetchall()
        return data, schedule, teams
    finally:
        con.close()


def fetch_store_snapshot(season, now):
    from local_model_source import fetch_local_snapshot
    root=Path(os.environ.get('NBA_STORE_ROOT','data/nba'))
    pin=os.environ.get('NBA_STORE_MANIFEST_SHA256')
    if pin is None:
        pin=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
    return fetch_local_snapshot(season,root,now,pin)


def finals(schedule, cutoff):
    result = {}
    for g in schedule.to_dict('records'):
        if str(g['status']).strip().lower() not in ('3', 'final', 'completed', 'complete', 'post'):
            continue
        date = dt.date.fromisoformat(str(g['game_date'])[:10])
        if date >= cutoff:
            continue
        gid = str(g['game_id'])
        if gid in result:
            raise ValueError('Duplicate completed schedule game')
        h, a = str(g['home_team_id']), str(g['away_team_id'])
        if h == a or any(t.strip().lower() in ('', 'none', 'nan', '<na>') for t in (h, a)):
            raise ValueError('Invalid completed schedule teams')
        result[gid] = (h, a, date)
    return result


def incomplete(data, expected, season):
    groups = {}
    for row in data.to_dict('records'):
        if str(row['season']) == str(season) and str(row['game_id']) in expected:
            groups.setdefault(str(row['game_id']), []).append(row)
    bad = []
    for gid, (home, away, date) in expected.items():
        rows = groups.get(gid, [])
        valid = len(rows) == 2 and {str(r['team_id']) for r in rows} == {home, away}
        scores = []
        if valid:
            both_home_flags_missing = all(r.get('home') is None for r in rows)
            for r in rows:
                try:
                    is_home = str(r['team_id']) == home
                    valid = valid and (both_home_flags_missing or
                        (type(r['home']) is bool and r['home'] == is_home))
                    valid = valid and str(r['opp_team_id']) == (away if is_home else home)
                    valid = valid and dt.date.fromisoformat(str(r['game_date'])[:10]) == date
                    for key in ('pts', 'off_rating', 'def_rating', 'pace'):
                        value = r[key]
                        if isinstance(value, bool) or not math.isfinite(float(value)):
                            valid = False
                        elif key == 'pts':
                            valid = valid and float(value) >= 0 and float(value).is_integer()
                        else:
                            valid = valid and float(value) > 0
                    scores.append(float(r['pts']))
                except (KeyError, TypeError, ValueError, OverflowError):
                    valid = False
            valid = valid and len(scores) == 2 and scores[0] != scores[1]
        if not valid:
            bad.append(gid)
    return sorted(bad)


def result_pair_exclusions(data, expected, season):
    blocked = set(incomplete(data, expected, season))
    counts = {}
    for row in data.to_dict('records'):
        gid = str(row['game_id'])
        if str(row['season']) == str(season) and gid in expected and row.get('home') is None:
            counts[gid] = counts.get(gid, 0) + 1
    return sorted(gid for gid, n in counts.items() if n == 2 and gid not in blocked)


def row_keys(data):
    return {(str(r['season']), str(r['game_id']), str(r['team_id']), str(r['game_date'])[:10])
            for r in data.to_dict('records')}


def load_checked(season, now, loader=None):
    local_mode = loader is None
    initial = fetch_store_snapshot(season,now) if local_mode else loader(season)
    expected = finals(initial[1], now.date())
    missing = incomplete(initial[0], expected, season)
    report = {'schema': 'paper-source-refresh-v1', 'source': SOURCE, 'read_attempts': 1,
              'status': 'not_needed', 'initial_incomplete_game_ids': missing,
              'unresolved_game_ids': missing, 'betting_release': False,
              'scope': 'Current-season known finals before UTC date; shared-model gate unchanged.'}
    report['excluded_home_away_result_game_ids'] = result_pair_exclusions(initial[0], expected, season)
    report['home_flag_policy'] = 'Two missing home flags remain null: team measurements retained, unchanged model pairing excludes result. One missing or contradictory flag remains blocked.'
    if local_mode:
        evidence=getattr(initial[0],'attrs',{}).get('nba_store_evidence')
        if (not isinstance(evidence,dict) or evidence.get('schema')!='local-model-source-v1'
                or not isinstance(evidence.get('manifest_sha256'),str)
                or not re.fullmatch(r'[0-9a-f]{64}',evidence['manifest_sha256'])
                or any(evidence.get(k) is not False for k in ('external_access_enabled','saved_store_modified','model_input_approved','betting_release'))):
            raise ValueError('Verified local store evidence required')
        report.update(source='local:nba-source-store',upstream_source=SOURCE,
            source_mode='local_frozen_snapshot',source_evidence=copy.deepcopy(evidence),
            scope='Frozen local model inputs; no network retry; shared-model freshness gate unchanged.')
        if missing:
            report['status']='local_snapshot_incomplete'
        return initial, report
    if not missing:
        return initial, report
    report.update(read_attempts=2, status='still_incomplete')
    try:
        candidate = loader(season)
        next_expected = finals(candidate[1], now.date())
        if any(next_expected.get(gid) != value for gid, value in expected.items()):
            raise ValueError('Refresh changed or removed previously completed schedule identities')
        if not row_keys(initial[0]).issubset(row_keys(candidate[0])):
            raise ValueError('Refresh lost previously loaded log identities')
        remaining = incomplete(candidate[0], next_expected, season)
        report['retry_incomplete_game_ids'] = remaining
        if not remaining:
            report.update(status='recovered', unresolved_game_ids=[],
                excluded_home_away_result_game_ids=result_pair_exclusions(candidate[0], next_expected, season))
            return candidate, report
    except Exception as exc:
        report.update(status='refresh_failed', error=(type(exc).__name__ + ': ' + str(exc))[:240])
    return initial, report
