"""Public daily paper-run reports; no invented assessments or release decisions."""
import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

FILES = {'paper': 'paper_latest.json', 'index': 'chat_index.json',
         'readiness': 'pipeline_readiness.json', 'health': 'paper_health.json'}


def stamp(value):
    t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timezone missing')
    return t


def cell(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\n', ' ')[:300]


def publish(root, now, started, pipeline_status):
    now = stamp(now) if isinstance(now, str) else now
    started = stamp(started)
    if now.tzinfo is None or started > now:
        raise ValueError('Invalid run times')
    root = Path(root)
    data, issues = {}, []
    for key, name in FILES.items():
        try:
            obj = json.loads((root / name).read_text())
            if not isinstance(obj, dict):
                raise ValueError('Expected object')
            data[key] = obj
        except (OSError, ValueError):
            data[key] = {}
            issues.append(name + ': fehlt oder ist unlesbar')
    p, idx, ready, health = (data[k] for k in FILES)
    generation = p.get('generated_at_utc')
    try:
        if not started <= stamp(generation) <= now:
            raise ValueError('Not this run')
    except (AttributeError, TypeError, ValueError):
        issues.append('Kein nachgewiesener neuer Datenstand aus diesem Lauf')
    if any(o.get('generated_at_utc') != generation or o.get('protocol') != p.get('protocol')
           for o in (idx, ready)):
        issues.append('Zeitstempel oder Protokolle der Teilberichte passen nicht zusammen')
    if health.get('source_generated_at_utc') != generation:
        issues.append('Health-Bericht gehoert nicht zum gleichen Datenstand')
    if any(o.get('execution_ok') is not True for o in (p, idx, ready)):
        issues.append('Mindestens ein Teilbericht meldet Ausfuehrungsfehler')
    if not isinstance(p.get('protocol'), str) or not p.get('protocol'):
        issues.append('Protokollkennung fehlt')
    fixtures = idx.get('fixtures')
    if not isinstance(fixtures, list) or any(not isinstance(f, dict) for f in fixtures):
        fixtures = []
        issues.append('Keine lesbare Begegnungsliste')
    forecasts = p.get('forecasts', [])
    if not isinstance(forecasts, list) or any(not isinstance(f, dict) for f in forecasts):
        forecasts = []
        issues.append('Keine lesbare Prognoseliste')
    if {str(f.get('game_id')) for f in fixtures} != {str(f.get('game_id')) for f in forecasts}:
        issues.append('Begegnungs- und Prognoselisten stimmen nicht ueberein')
    if any(not re.fullmatch(r'002\d{7}', str(f.get('game_id'))) for f in fixtures + forecasts):
        issues.append('Ungueltige Begegnungskennung')
    current_data = not issues
    stages_ok = pipeline_status == 'success'
    if not stages_ok:
        issues.append('Workflow vor Veroeffentlichung nicht erfolgreich: ' + cell(pipeline_status))
    local = now.astimezone(ZoneInfo('Europe/Berlin'))
    date = local.date().isoformat()
    lines = ['# NBA-Tagesbericht ' + date, '',
        'Bericht erstellt: ' + local.isoformat(timespec='seconds') + ' (Europe/Berlin).',
        'Laufbeginn UTC: ' + started.isoformat() + '.', '',
        '## Betriebsstand', '',
        'Workflow vor Veroeffentlichung: ' + cell(pipeline_status) + '.',
        'Quellstand UTC: ' + cell(generation or 'unbekannt') + '.',
        'Health-Status: ' + cell(health.get('status', 'unbekannt')) + '.', '',
        'Keine Echtgeldfreigabe. Papierberechnung ist keine abgeschlossene fachliche Bewertung.', '']
    if issues:
        lines += ['## Fehler / eingeschraenkter Lauf', ''] + ['- ' + x for x in issues] + ['',
            'Fehlerstatus bleibt sichtbar; nur zeitlich und strukturell passende Teilberichte erscheinen unten.', '']
    if current_data:
        lines += ['## Erfassung und Berechnung', '',
            'Anstehende Spiele laut Quelle: ' + cell(p.get('upcoming_schedule_games', 'unbekannt')) + '.',
            'Prognosen: ' + str(len(forecasts)) + '; uebersprungen: ' + str(len(p.get('skipped_games', []))) + '.',
            'Referenzangebote: ' + cell(idx.get('actual_offer_count', 'unbekannt')) +
            '; experimentell berechnet: ' + cell(idx.get('computed_offer_count', 'unbekannt')) + '.', '',
            'Der Umfang folgt dem gespeicherten Lauf; der Bericht erfindet keine vollstaendige Alternativmarktabdeckung.', '',
            '## Begegnungen', '',
            '| Beginn Berlin | Begegnung | Angebote | Sieger | Handicap | Gesamtpunkte |',
            '|---|---|---:|---|---|---|']
        by_id = {f.get('game_id'): f for f in forecasts}
        progress = ready.get('fixtures', [])
        progress = progress if isinstance(progress, list) else []
        coverage = {f.get('game_id'): f.get('markets', {}) for f in progress if isinstance(f, dict)}
        for f in fixtures:
            gid = f.get('game_id')
            try:
                tip = stamp(by_id[gid]['start_time_utc']).astimezone(ZoneInfo('Europe/Berlin'))
                tip_text = tip.strftime('%d.%m. %H:%M') + (' (begonnen)' if tip <= now else '')
            except (KeyError, TypeError, AttributeError, ValueError):
                tip_text = 'unbekannt'
            markets = coverage.get(gid, {})
            values = []
            for market in ('moneyline', 'spread', 'total'):
                m = markets.get(market, {}) if isinstance(markets, dict) else {}
                if not isinstance(m, dict):
                    m = {}
                state = m.get('assessment', 'not_recorded_by_pipeline')
                values.append(cell(str(m.get('computed', '?')) + '/' + str(m.get('offers', '?')) +
                    ' Papierberechnungen; Bewertung: ' +
                    ('nicht dokumentiert' if state == 'not_recorded_by_pipeline' else str(state))))
            lines.append('| ' + ' | '.join([cell(tip_text), cell(str(f.get('away')) + ' bei ' + str(f.get('home'))),
                cell(f.get('offer_count', '?'))] + values) + ' |')
        lines += ['', '## Fachlicher Abschluss', '',
            'Dieser Renderer fuehrt keine Personalrecherche durch und erzeugt keine unabhaengigen Linienwahrscheinlichkeiten oder Empfehlungen.',
            'Fehlende Bewertungen werden nicht in AUSLASSEN oder BEOBACHTEN umbenannt. Keine Freigabe aus unvalidierten Papierwerten.',
            'Detaildaten: [Marktindex](../chat_index.json), [Pruefstand](../pipeline_readiness.json), [Papierauswertung](../paper_evaluation.json).', '']
    lines += ['## Abnahmegrenze', '',
        'Der Tagesbericht dokumentiert den gespeicherten Lauf, nicht die erfolgreiche Ausfuehrung noch fehlender Analyseschritte.',
        'Ein fehlerhafter Lauf bleibt fehlerhaft; die Veroeffentlichung setzt seinen Status nicht auf erfolgreich.', '']
    target = root / 'daily'
    target.mkdir(parents=True, exist_ok=True)
    body = '\n'.join(lines)
    (target / (date + '.md')).write_text(body)
    (target / 'latest.md').write_text(body)
    dates = sorted((x.stem for x in target.glob('*.md') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', x.stem)), reverse=True)
    archive = '# Oeffentliche NBA-Tagesberichte\n\n[Aktueller Bericht](latest.md)\n\n' + '\n'.join('- [' + d + '](' + d + '.md)' for d in dates) + '\n'
    (target / 'README.md').write_text(archive)
    return not issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='reports')
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    started = os.environ.get('NBA_RUN_STARTED_AT', now.isoformat())
    ok = publish(args.root, now, started, os.environ.get('NBA_PIPELINE_STATUS', 'unknown'))
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
