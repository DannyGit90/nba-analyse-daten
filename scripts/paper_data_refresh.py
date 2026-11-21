"""One bounded source refresh before the existing shared-model freshness gate."""
import datetime as dt
import math

SOURCE = 'https://basketball-data.billmill.org/nba/nba.duckdb'
LOG_SQL = "SELECT season, game_id, team_id, opp_team_id, game_date, home, pts, off_rating, def_rating, pace FROM nba.team_game_logs WHERE season BETWEEN 2010 AND ? AND CAST(game_id AS VARCHAR) LIKE '002%'"
SCHEDULE_SQL = "SELECT game_id, game_date, start_time, home_team_id, away_team_id, neutral_site, status FROM nba.schedule WHERE season = ? AND CAST(game_id AS VARCHAR) LIKE '002%'"


def fetch_snapshot(season):
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
            for r in rows:
                try:
                    is_home = str(r['team_id']) == home
                    valid = valid and type(r['home']) is bool and r['home'] == is_home
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


def row_keys(data):
    return {(str(r['season']), str(r['game_id']), str(r['team_id']), str(r['game_date'])[:10])
            for r in data.to_dict('records')}


def load_checked(season, now, loader=None):
    loader = loader or fetch_snapshot
    initial = loader(season)
    expected = finals(initial[1], now.date())
    missing = incomplete(initial[0], expected, season)
    report = {'schema': 'paper-source-refresh-v1', 'source': SOURCE, 'read_attempts': 1,
              'status': 'not_needed', 'initial_incomplete_game_ids': missing,
              'unresolved_game_ids': missing, 'betting_release': False,
              'scope': 'Current-season known finals before UTC date; shared-model gate unchanged.'}
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
            report.update(status='recovered', unresolved_game_ids=[])
            return candidate, report
    except Exception as exc:
        report.update(status='refresh_failed', error=(type(exc).__name__ + ': ' + str(exc))[:240])
    return initial, report
