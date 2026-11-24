"""Persistent, versioned NBA source tables. Capture only; no model release."""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = 'https://basketball-data.billmill.org/nba/nba.duckdb'
SCHEMA = 'nba-source-store-v1'
MAX_ROWS = 200000
MAX_BYTES = 20000000
PLAYER_FIELDS = 'season,game_id,player_id,team_id,opp_team_id,game_date,min,pts,fgm,fga,fg3m,fg3a,ftm,fta,oreb,dreb,reb,ast,tov,stl,blk,pf'


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def stamp(value):
    result = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone missing')
    return result


def rows(con, sql, args=()):
    cur = con.execute(sql, args)
    values = cur.fetchmany(MAX_ROWS + 1)
    if len(values) > MAX_ROWS:
        raise ValueError('Row limit exceeded; never truncate')
    names = [c[0] for c in cur.description]
    def scalar(v):
        if isinstance(v, (dt.datetime, dt.date)):
            return v.isoformat()
        return v
    return [{k: scalar(v) for k, v in zip(names, row)} for row in values]


def unique(values, keys):
    seen = set()
    for row in values:
        key = tuple(row[k] for k in keys)
        if any(v is None or v == '' for v in key) or key in seen:
            raise ValueError('Missing or duplicate key: ' + str(keys))
        seen.add(key)
        for k, v in row.items():
            if k.endswith('_id') and v is not None and (not isinstance(v, str) or not v.strip()):
                raise ValueError('IDs must remain nonempty strings')
    return values


def inspect_catalog(catalog):
    if not catalog:
        raise ValueError('Player catalog is empty: rows=0')
    if len(catalog) > 20000:
        raise ValueError('Player catalog exceeds 20000 rows: rows=' + str(len(catalog)))
    issues = [{'player_id': r['player_id'], 'reason': 'missing_or_invalid_name'} for r in catalog
              if not isinstance(r.get('name'), str) or not r['name'].strip()]
    quality = {'rows': len(catalog), 'usable_name_rows': len(catalog)-len(issues),
               'unusable_name_rows': len(issues), 'name_issues': issues}
    if quality['usable_name_rows'] == 0:
        raise ValueError('Player catalog has no usable names: rows=' + str(len(catalog)))
    return quality


def read_store(root):
    root = Path(root)
    path = root / 'manifest.json'
    if not path.exists():
        if root.exists() and any(root.rglob('*.jsonl')):
            raise ValueError('Unmanifested data; refusing bootstrap')
        return {}, {}
    manifest = json.loads(path.read_text())
    if manifest.get('schema') != SCHEMA:
        raise ValueError('Unknown store schema')
    data = {}
    for name, proof in manifest['tables'].items():
        if not re.fullmatch(r'(players|[a-z_]+/season=\d{4})\.jsonl', name):
            raise ValueError('Unsafe table path')
        file = root / name
        if file.is_symlink():
            raise ValueError('Symlink table rejected')
        body = file.read_bytes()
        if len(body) > MAX_BYTES or sha(body) != proof['sha256']:
            raise ValueError('Stored table hash or size mismatch')
        values = [json.loads(line) for line in body.splitlines()]
        if len(values) != proof['rows']:
            raise ValueError('Stored table row count mismatch')
        data[name] = values
    return manifest, data


def capture(con, old, now, diagnostics=None):
    diagnostics = {} if diagnostics is None else diagnostics
    diagnostics['stage'] = 'source_metadata'
    if now.tzinfo is None:
        raise ValueError('Aware clock required')
    today = now.astimezone(ZoneInfo('America/New_York')).date()
    season = today.year + int(today.month >= 10)
    names = ('team_seasons', 'rosters_daily', 'schedule', 'team_game_logs', 'player_game_logs')
    marks = ','.join('?' for _ in names)
    metadata = rows(con, 'SELECT dataset,source,updated FROM nba.main.metadata WHERE dataset IN (' + marks + ') ORDER BY dataset', names)
    if {r['dataset'] for r in metadata} != set(names):
        raise ValueError('Missing dataset metadata')
    for m in metadata:
        if not now - dt.timedelta(hours=72) <= stamp(m['updated']) <= now:
            raise ValueError('Stale or future upstream metadata: ' + m['dataset'])
    data = dict(old)
    diagnostics['stage'] = 'player_catalog'
    catalog = unique(rows(con, 'SELECT player_id,name,first_season,last_season FROM nba.main.players ORDER BY player_id'), ('player_id',))
    diagnostics['catalog_rows'] = len(catalog)
    diagnostics['catalog_quality'] = inspect_catalog(catalog)
    for row in catalog:
        row['identity_name_usable'] = isinstance(row.get('name'), str) and bool(row['name'].strip())
    previous = {r['player_id']: r for r in old.get('players.jsonl', [])}
    current = {r['player_id']: dict(r, source_present=True) for r in catalog}
    registry = {pid: dict(r, source_present=False) for pid, r in previous.items()}
    registry.update(current)
    data['players.jsonl'] = sorted(registry.values(), key=lambda r: r['player_id'])
    pids = set(current)
    diagnostics['stage'] = 'team_mapping'
    teams = unique(rows(con, 'SELECT * FROM nba.main.team_seasons WHERE season=? AND is_nba=true ORDER BY team_id', (season,)), ('season', 'team_id'))
    tids = {r['team_id'] for r in teams}
    if len(tids) != 30:
        raise ValueError('Expected all 30 NBA teams; no partial promotion')
    data[f'team_seasons/season={season}.jsonl'] = teams
    diagnostics['stage'] = 'league_rosters'
    rosters = unique(rows(con, 'SELECT r.* FROM nba.main.rosters_daily r JOIN nba.main.team_seasons t ON r.season=t.season AND r.team_id=t.team_id WHERE r.season=? AND t.is_nba=true ORDER BY r.as_of_date,r.player_id,r.team_id', (season,)), ('season', 'as_of_date', 'player_id'))
    if not rosters or any(r['season'] != season or r['player_id'] not in pids or r['team_id'] not in tids or dt.date.fromisoformat(r['as_of_date']) > today for r in rosters):
        raise ValueError('Invalid roster references or dates')
    latest = max(r['as_of_date'] for r in rosters)
    active = [r for r in rosters if r['as_of_date'] == latest]
    if {r['team_id'] for r in active} != tids or (today - dt.date.fromisoformat(latest)).days > 3:
        raise ValueError('Incomplete or stale latest league roster snapshot')
    roster_name = f'rosters_daily/season={season}.jsonl'
    old_rosters = old.get(roster_name, [])
    if old_rosters and latest < max(r['as_of_date'] for r in old_rosters):
        raise ValueError('Roster date regressed')
    incoming_dates = {r['as_of_date'] for r in rosters}
    retained = [r for r in old_rosters if r['as_of_date'] not in incoming_dates]
    data[roster_name] = sorted(retained + rosters, key=lambda r: (r['as_of_date'], r['player_id']))
    diagnostics['stage'] = 'schedule'
    schedule = unique(rows(con, 'SELECT * FROM nba.main.schedule WHERE season=? ORDER BY game_id', (season,)), ('season', 'game_id'))
    if not schedule:
        raise ValueError('Empty schedule')
    for r in schedule:
        if r['season'] != season or not re.fullmatch(r'\d{10}', r['game_id']):
            raise ValueError('Invalid schedule identity')
    data[f'schedule/season={season}.jsonl'] = schedule
    diagnostics['stage'] = 'team_game_logs'
    for year in range(season - 4, season + 1):
        name = f'team_game_logs/season={year}.jsonl'
        if year == season or name not in old:
            data[name] = unique(rows(con, "SELECT * FROM nba.main.team_game_logs WHERE season=? AND game_id LIKE '002%' ORDER BY game_id,team_id", (year,)), ('season', 'game_id', 'team_id'))
    diagnostics['stage'] = 'player_game_logs'
    for year in (season - 1, season):
        name = f'player_game_logs/season={year}.jsonl'
        if year == season or name not in old:
            data[name] = unique(rows(con, 'SELECT ' + PLAYER_FIELDS + " FROM nba.main.player_game_logs WHERE season=? AND game_id LIKE '002%' ORDER BY game_id,player_id", (year,)), ('season', 'game_id', 'player_id'))
    for name, values in data.items():
        if name.startswith(('player_game_logs/', 'team_game_logs/')):
            year = int(name.split('=')[1].split('.')[0])
            for r in values:
                if r['season'] != year or not re.fullmatch(r'002\d{7}', r['game_id']) or dt.date.fromisoformat(r['game_date']) > today:
                    raise ValueError('Invalid historical game identity or future date')
                if name.startswith('player_game_logs/') and r['player_id'] not in registry:
                    raise ValueError('Unknown player ID in game logs')
    for name, values in data.items():
        if name.startswith(('schedule/', 'team_game_logs/', 'player_game_logs/')):
            keys = ('season', 'game_id', 'player_id') if name.startswith('player_game_logs/') else ('season', 'game_id', 'team_id') if name.startswith('team_game_logs/') else ('season', 'game_id')
            previous_keys = {tuple(r[k] for k in keys) for r in old.get(name, [])}
            incoming_keys = {tuple(r[k] for k in keys) for r in values}
            if not previous_keys <= incoming_keys:
                raise ValueError('Source lost stored game keys: ' + name)
    before = {}
    if old_rosters:
        old_latest = max(r['as_of_date'] for r in old_rosters)
        before = {r['player_id']: r['team_id'] for r in old_rosters if r['as_of_date'] == old_latest}
    after = {r['player_id']: r['team_id'] for r in active}
    changes = {'new_source_player_ids': sorted(pids - set(previous)),
        'source_catalog_absent_ids_retained': sorted(set(previous) - pids),
        'roster_baseline': not bool(old_rosters),
        'roster_changes': [{'player_id': pid, 'previous_team_id': before.get(pid), 'observed_team_id': after.get(pid)} for pid in sorted(set(before) | set(after)) if before.get(pid) != after.get(pid)]}
    return data, {'season': season, 'roster_date': latest, 'roster_team_count': len(tids), 'roster_player_count': len(active), 'source_metadata': metadata, 'changes': changes}


def prepare(source_root, stage_root, con, now, run_id, code_sha, diagnostics=None):
    diagnostics = {} if diagnostics is None else diagnostics
    diagnostics['stage'] = 'saved_store'
    manifest, old = read_store(source_root)
    if manifest and stamp(manifest['observed_at_utc']) > now:
        raise ValueError('Observation clock regressed')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id):
        raise ValueError('Unsafe run ID')
    data, evidence = capture(con, old, now, diagnostics)
    diagnostics['stage'] = 'serialization'
    contents, proofs = {}, {}
    for name, values in data.items():
        body = ''.join(encoded(r) + '\n' for r in values).encode()
        if len(body) > MAX_BYTES:
            raise ValueError('Table byte limit exceeded')
        contents[name] = body
        proofs[name] = {'rows': len(values), 'sha256': sha(body)}
    if sum(len(b) for b in contents.values()) > 100000000:
        raise ValueError('Total storage budget exceeded; no partial promotion')
    result = dict(schema=SCHEMA, execution_ok=True, observed_at_utc=now.isoformat(), run_id=run_id, code_sha=code_sha,
        source=SOURCE, source_read_only=True, source_transaction_verified=False, historical_publication_verified=False,
        model_input_approved=False, betting_release=False, tables=proofs, **evidence)
    stage = Path(stage_root)
    if stage.resolve() == Path(source_root).resolve() or stage.exists():
        raise ValueError('Fresh staging path separate from saved store required')
    stage.mkdir(parents=True)
    for name, body in contents.items():
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    (stage / 'manifest.json').write_text(encoded(result) + '\n')
    read_store(stage)
    diagnostics['stage'] = 'prepared'
    result['diagnostics'] = diagnostics
    (stage / 'manifest.json').write_text(encoded(result) + '\n')
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source-root', default='data/nba')
    p.add_argument('--stage-root', required=True)
    p.add_argument('--report', required=True)
    a = p.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    report = {'schema': SCHEMA, 'execution_ok': False, 'observed_at_utc': now.isoformat(), 'betting_release': False, 'saved_store_modified': False}
    diagnostics = {'stage': 'open_source'}
    report['diagnostics'] = diagnostics
    con = None
    try:
        import duckdb
        con = duckdb.connect()
        con.execute("ATTACH '" + SOURCE + "' AS nba (READ_ONLY)")
        report = prepare(a.source_root, a.stage_root, con, now, os.environ['NBA_STORE_RUN_ID'], os.environ['NBA_STORE_CODE_SHA'], diagnostics)
        report['saved_store_modified'] = False
    except Exception as exc:
        report['error'] = (type(exc).__name__ + ': ' + str(exc))[:800]
    finally:
        if con is not None:
            con.close()
    target = Path(a.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(encoded(report) + '\n')
    raise SystemExit(0 if report['execution_ok'] else 1)


if __name__ == '__main__':
    main()
