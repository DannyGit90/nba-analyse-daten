import datetime as dt
import hashlib
import json
import tempfile
from pathlib import Path
import duckdb

now = dt.datetime.now(dt.timezone.utc)
last = now.year + int(now.month >= 10)
report = {'checked_at_utc': now.isoformat(), 'source': 'https://basketball-data.billmill.org/nba/nba.duckdb', 'first_season_end_year': 2010, 'last_season_end_year': last, 'seasons': [], 'ok': False, 'raw_data_published': False, 'model_trained': False}
with tempfile.TemporaryDirectory() as tmp:
    con = duckdb.connect(str(Path(tmp) / 'history.duckdb'))
    try:
        con.execute("ATTACH 'https://basketball-data.billmill.org/nba/nba.duckdb' AS nba")
        initialized = False
        for season in range(2010, last + 1):
            item = {'season': season, 'loaded': False}
            try:
                con.execute("CREATE OR REPLACE TEMP TABLE incoming AS SELECT * FROM nba.team_game_logs WHERE season = ? AND CAST(game_id AS VARCHAR) LIKE '002%'", [season])
                count, games, teams, first, latest, missing_home = con.execute('SELECT count(*), count(DISTINCT game_id), count(DISTINCT team_id), min(game_date), max(game_date), count(*) FILTER (WHERE home IS NULL) FROM incoming').fetchone()
                duplicates = con.execute('SELECT count(*) FROM (SELECT game_id, team_id FROM incoming GROUP BY 1, 2 HAVING count(*) > 1)').fetchone()[0]
                unpaired = con.execute('SELECT count(*) FROM (SELECT game_id FROM incoming GROUP BY 1 HAVING count(*) != 2)').fetchone()[0]
                bad_home = con.execute('SELECT count(*) FROM (SELECT game_id FROM incoming GROUP BY 1 HAVING count(*) FILTER (WHERE home IS NOT NULL) = 2 AND sum(CASE WHEN home THEN 1 ELSE 0 END) != 1)').fetchone()[0]
                missing_scores = con.execute('SELECT count(*) FROM incoming WHERE pts IS NULL OR plus_minus IS NULL').fetchone()[0]
                inconsistent = con.execute('SELECT count(*) FROM incoming a JOIN incoming b ON a.game_id = b.game_id AND a.opp_team_id = b.team_id WHERE a.pts - b.pts != a.plus_minus OR a.team_id != b.opp_team_id').fetchone()[0]
                orphan_rows = con.execute('SELECT count(*) FROM incoming a WHERE NOT EXISTS (SELECT 1 FROM incoming b WHERE a.game_id = b.game_id AND a.opp_team_id = b.team_id AND b.opp_team_id = a.team_id)').fetchone()[0]
                rows = con.execute('SELECT * FROM incoming ORDER BY game_id, team_id').fetchall()
                digest = hashlib.sha256(json.dumps(rows, default=str, separators=(',', ':')).encode()).hexdigest()
                if count:
                    if not initialized:
                        con.execute('CREATE TABLE history AS SELECT * FROM incoming')
                        initialized = True
                    else:
                        con.execute('INSERT INTO history BY NAME SELECT * FROM incoming')
                item.update(loaded=count > 0, rows=count, games=games, teams=teams, first_game=str(first), latest_game=str(latest), missing_home_rows=missing_home, duplicate_keys=duplicates, unpaired_games=unpaired, invalid_home_games=bad_home, missing_score_rows=missing_scores, inconsistent_score_rows=inconsistent, orphan_opponent_rows=orphan_rows, content_sha256=digest)
                item['basic_checks_ok'] = count > 0 and teams == 30 and not any([duplicates, unpaired, bad_home, missing_scores, inconsistent, orphan_rows])
            except Exception as exc:
                item.update(error_type=type(exc).__name__, error=str(exc)[:3000], basic_checks_ok=False)
            report['seasons'].append(item)
        if initialized:
            report['total_rows_loaded'] = con.execute('SELECT count(*) FROM history').fetchone()[0]
            report['total_games_loaded'] = con.execute('SELECT count(*) FROM (SELECT DISTINCT season, game_id FROM history)').fetchone()[0]
        report['ok'] = all(s.get('basic_checks_ok', False) for s in report['seasons'])
    except Exception as exc:
        report.update(error_type=type(exc).__name__, error=str(exc)[:6000])
    finally:
        con.close()
report['limitations'] = ['Counts do not prove complete schedules; external completeness checks remain required.', 'Missing home flags are reported, not imputed.', 'No historical injury snapshots, odds, calibration or model validation.', 'Raw historical database is temporary and removed after this diagnostic; future model runs must reload the source.', 'No scheduled updates enabled.']
Path('diagnostics').mkdir(exist_ok=True)
Path('diagnostics/history_access.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2, ensure_ascii=False))
