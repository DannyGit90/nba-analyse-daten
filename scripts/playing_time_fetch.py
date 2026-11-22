"""Bounded read-only player-time queries; no model or unit approval."""

KEY_FIELDS = ('season', 'game_id', 'player_id', 'team_id')


def fetch_exact(connection, table, keys, max_rows=200):
    if table not in ('player_game_logs', 'player_box'):
        raise ValueError('Unsupported player-time table')
    if not isinstance(keys, list) or type(max_rows) is not int or not 1 <= max_rows <= 200:
        raise ValueError('Invalid requested keys or row bound')
    if len(keys) > 200:
        raise ValueError('Requested-key resource limit exceeded')
    if not keys:
        return []
    seen = set()
    for key in keys:
        if not isinstance(key, dict) or type(key.get('season')) is not int:
            raise ValueError('Invalid requested composite key')
        if any(not isinstance(key.get(k), str) or not key[k] or key[k] != key[k].strip() for k in KEY_FIELDS[1:]):
            raise ValueError('Invalid requested composite key')
        value = tuple(key[k] for k in KEY_FIELDS)
        if value in seen:
            raise ValueError('Duplicate requested composite keys')
        seen.add(value)
    actual = dict(connection.execute(
        "SELECT column_name,data_type FROM duckdb_columns() WHERE database_name='nba' AND schema_name='main' AND table_name=?",
        [table]).fetchall())
    columns = KEY_FIELDS + (('game_date', 'min') if table == 'player_game_logs' else ('seconds_played',))
    if not all(k in actual for k in columns):
        raise ValueError('Required source column missing')
    if table == 'player_box' and actual['seconds_played'] != 'INTEGER':
        raise ValueError('seconds_played source type is not INTEGER')
    if table == 'player_game_logs' and actual['min'] not in ('DOUBLE', 'FLOAT', 'REAL'):
        raise ValueError('min source type is not floating numeric')
    values = ','.join('(CAST(? AS INTEGER),CAST(? AS VARCHAR),CAST(? AS VARCHAR),CAST(? AS VARCHAR))' for _ in keys)
    params = [key[k] for key in keys for k in KEY_FIELDS]
    join = ' AND '.join('src.' + k + ' IS NOT DISTINCT FROM chosen.' + k for k in KEY_FIELDS)
    projection = ', '.join('src.' + k for k in columns)
    order = ', '.join('src.' + k for k in KEY_FIELDS)
    sql = ('WITH chosen(season,game_id,player_id,team_id) AS (VALUES ' + values + ') SELECT ' + projection
           + ' FROM nba.main.' + table + ' AS src JOIN chosen ON ' + join + ' ORDER BY ' + order + ' LIMIT ?')
    cursor = connection.execute(sql, params + [max_rows + 1])
    found = cursor.fetchall()
    if len(found) > max_rows:
        raise ValueError('Source-row resource limit exceeded; refusing truncated comparison')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in found]
