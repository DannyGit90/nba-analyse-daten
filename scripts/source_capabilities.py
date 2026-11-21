"""Read-only source inventory; column names are leads, not semantic validation."""
import datetime as dt
import json
from pathlib import Path

SOURCE = 'https://basketball-data.billmill.org/nba/nba.duckdb'
SQL = "SELECT schema_name, table_name, column_name, data_type FROM duckdb_columns() WHERE database_name = 'nba' AND internal = false ORDER BY schema_name, table_name, column_index"


def inventory(connection):
    tables = {}
    for schema, table, column, dtype in connection.execute(SQL).fetchall():
        key = (schema, table)
        tables.setdefault(key, []).append({'name':column, 'type':dtype})
    result = []
    for (schema, name), columns in sorted(tables.items()):
        names = {c['name'].lower() for c in columns}
        hints = []
        player = bool(names & {'player_id', 'person_id', 'athlete_id'})
        if player:
            hints.append('possible_player_identity')
        if player and names & {'game_id', 'event_id'}:
            hints.append('possible_player_game_records')
        if player and 'team_id' in names:
            hints.append('possible_player_team_link')
        if player and names & {'min', 'minutes', 'minutes_played'}:
            hints.append('possible_playing_time')
        if any(x in name.lower() for x in ('injur', 'roster', 'availab', 'transaction')):
            hints.append('possible_personnel_table_name')
        result.append({'schema':schema, 'table':name, 'columns':columns,
                       'candidate_hints':hints, 'semantics_verified':False})
    if not result:
        raise ValueError('No user table columns found in attached source')
    return result


def audit(now, connector=None):
    report = {'schema':'source-capabilities-v1', 'checked_at_utc':now.isoformat(),
        'source':SOURCE, 'execution_ok':False, 'read_only':True, 'tables':[],
        'player_data_rows_imported':0, 'historical_pregame_personnel_verified':False,
        'production_model_changed':False, 'betting_release':False,
        'limitations':['Schema inventory only; candidate column names do not establish player identity, data quality, time coverage or as-of availability.',
                      'No player training data imported; no prediction or recommendation produced.']}
    con = None
    try:
        if connector is None:
            import duckdb
            connector = duckdb.connect
        con = connector()
        con.execute("ATTACH '"+SOURCE+"' AS nba (READ_ONLY)")
        report['tables'] = inventory(con)
        report['table_count'] = len(report['tables'])
        report['candidate_table_count'] = sum(bool(t['candidate_hints']) for t in report['tables'])
        report['execution_ok'] = True
    except Exception as exc:
        report['error'] = (type(exc).__name__+': '+str(exc))[:600]
    finally:
        if con is not None:
            con.close()
    return report


def write_report(report, root=Path('diagnostics')):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    (root/'source_capabilities.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# Datenquellen-Bestandspruefung', '', 'Pruefzeit UTC: '+report['checked_at_utc'],
        'Quelle: '+report['source'], 'Ausfuehrung erfolgreich: '+str(report['execution_ok']),
        'Nur Tabellen/Spalten inventarisiert. Keine Spielerdaten importiert oder fachlich freigegeben.', '']
    if report.get('error'):
        lines += ['Fehler: '+report['error'].replace('\n',' ') , '']
    for t in report['tables']:
        lines += ['## '+t['schema']+'.'+t['table'],
            'Suchhinweise: '+(', '.join(t['candidate_hints']) or 'keine'),
            'Spalten: '+', '.join(c['name']+' ('+c['type']+')' for c in t['columns']), '']
    lines += ['Naechster Schritt: gefundene Kandidaten gezielt mit echten Datensaetzen auf Identitaet, Einsatzdaten und Zeitbezug pruefen. Keine Verfuegbarkeit allein aus Spaltennamen ableiten.', '']
    (root/'source_capabilities.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    report = audit(dt.datetime.now(dt.timezone.utc))
    write_report(report)
    raise SystemExit(0 if report['execution_ok'] else 1)


if __name__ == '__main__':
    main()
