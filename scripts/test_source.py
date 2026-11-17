import datetime as dt
import hashlib
import json
from pathlib import Path
import duckdb

SOURCE = 'https://basketball-data.billmill.org/nba/nba.duckdb'
now = dt.datetime.now(dt.timezone.utc)
season = now.year + (1 if now.month >= 10 else 0)
report = {'checked_at_utc': now.isoformat(), 'source': SOURCE, 'season': season, 'ok': False, 'scope': 'source access diagnostic, not model validation', 'raw_data_published': False}
try:
    con = duckdb.connect()
    con.execute("ATTACH 'https://basketball-data.billmill.org/nba/nba.duckdb' AS nba")
    con.execute("CREATE TABLE snapshot AS SELECT * FROM nba.team_game_logs WHERE season = ? AND CAST(game_id AS VARCHAR) LIKE '002%'", [season])
    cols = [x[0] for x in con.description] if False else [x[0] for x in con.execute('SELECT * FROM snapshot LIMIT 0').description]
    rows = con.execute('SELECT * FROM snapshot ORDER BY game_id, team_id').fetchall()
    counts = con.execute('SELECT count(*), count(DISTINCT game_id), count(DISTINCT team_id), min(game_date), max(game_date), count(*) FILTER (WHERE home IS NULL) FROM snapshot').fetchone()
    duplicates = con.execute('SELECT count(*) FROM (SELECT game_id, team_id FROM snapshot GROUP BY 1, 2 HAVING count(*) > 1)').fetchone()[0]
    unpaired = con.execute('SELECT count(*) FROM (SELECT game_id FROM snapshot GROUP BY 1 HAVING count(*) != 2)').fetchone()[0]
    report.update(rows=counts[0], games=counts[1], teams=counts[2], first_game=str(counts[3]), latest_game=str(counts[4]), missing_home_rows=counts[5], duplicate_keys=duplicates, unpaired_games=unpaired, columns=cols, content_sha256=hashlib.sha256(json.dumps(rows, default=str, separators=(',', ':')).encode()).hexdigest())
    report['ok'] = counts[0] > 0 and counts[2] == 30 and duplicates == 0 and unpaired == 0
    report['freshness_requires_review'] = True
    report['note'] = 'Success proves source retrieval on this runner only. Freshness, licensing, GitHub-to-chat transfer and model quality remain unverified.'
except Exception as exc:
    report['error_type'] = type(exc).__name__
    report['error'] = str(exc)[:6000]
Path('diagnostics').mkdir(exist_ok=True)
Path('diagnostics/source_access.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2, ensure_ascii=False))
