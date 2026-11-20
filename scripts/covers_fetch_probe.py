"""Current-fixture transport/parser probe; never publishes offers or forecasts."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

OUTPUT = Path('reports/covers_fetch_probe.json')
BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='


def stamp(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


def select_fixture(paper, index, now):
    if any(paper.get(k) != index.get(k) for k in ('generated_at_utc', 'protocol')):
        raise ValueError('Forecast and index snapshots differ')
    forecasts = sorted((f for f in paper['forecasts'] if stamp(f['start_time_utc']) > now),
                       key=lambda f: (stamp(f['start_time_utc']), f['game_id']))
    for fixture in forecasts:
        for error in index.get('source_errors', []):
            url = error.get('source', '')
            if error.get('game_id') == fixture['game_id'] and re.fullmatch(
                    r'https://www\.covers\.com/sport/basketball/nba/matchup/\d+/odds', url):
                return fixture, url
    raise ValueError('No future fixture with a recorded matching Covers URL; no stale fallback URL used')


def fetch(url, timeout):
    request = Request(url, headers={'User-Agent': 'nba-research/1.0'})
    with urlopen(request, timeout=timeout) as response:
        body = response.read(4000001)
        if len(body) > 4000000:
            raise ValueError('Response exceeds size limit')
        metadata = {'requested_url': url, 'final_url': response.geturl(),
                    'http_status': response.status, 'bytes': len(body),
                    'sha256': hashlib.sha256(body).hexdigest(),
                    'headers': {k: response.headers.get(k) for k in
                                ('Content-Type', 'Date', 'Cache-Control', 'Vary')
                                if response.headers.get(k) is not None}}
    return body.decode('utf-8'), metadata


def summarize_espn(payload, fixture, now):
    aliases = {'GS': 'GSW', 'NY': 'NYK', 'NO': 'NOP', 'SA': 'SAS', 'UTAH': 'UTA', 'WSH': 'WAS'}
    result = {'events_total': 0, 'team_matches': 0, 'exact_time_matches': 0,
              'pregame_matches': 0, 'odds_blocks': 0, 'samples': []}
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        return dict(result, diagnosis='unexpected_top_level_schema')
    result['events_total'] = len(payload['events'])
    for event in payload['events']:
        for competition in event.get('competitions', []):
            teams = {c['homeAway']: aliases.get(c['team']['abbreviation'], c['team']['abbreviation'])
                     for c in competition.get('competitors', [])}
            if (teams.get('home'), teams.get('away')) != (fixture['home'], fixture['away']):
                continue
            result['team_matches'] += 1
            date = competition.get('date', event.get('date'))
            state = competition.get('status', event.get('status', {})).get('type', {}).get('state')
            exact = bool(date) and stamp(date) == stamp(fixture['start_time_utc'])
            result['exact_time_matches'] += int(exact)
            pregame = exact and state == 'pre' and stamp(fixture['start_time_utc']) > now
            result['pregame_matches'] += int(pregame)
            odds = competition.get('odds', [])
            if pregame and isinstance(odds, list):
                result['odds_blocks'] += len(odds)
            if len(result['samples']) < 2:
                result['samples'].append({'date': date, 'state': state,
                    'competition_keys': sorted(competition)[:30],
                    'odds_type': type(odds).__name__,
                    'odds_sample_json': json.dumps(odds, ensure_ascii=True)[:1500]})
    result['diagnosis'] = ('no_events' if not result['events_total'] else
        'no_team_match' if not result['team_matches'] else
        'start_time_mismatch' if not result['exact_time_matches'] else
        'not_pregame' if not result['pregame_matches'] else
        'no_expected_odds_blocks' if not result['odds_blocks'] else
        'odds_blocks_present_check_collector_output')
    return result


def summarize_covers(html, fixture, url, now):
    from covers_review import Document, parse
    document = Document()
    document.feed(html)
    rows = [value for kind, value in document.events if kind == 'row' and len(value) == 3]
    samples = []
    result = {'title': document.title[:180], 'three_cell_rows': len(rows),
              'percent_cells': sum('%' in cell for row in rows for cell in row[1:]),
              'provider_row_samples': [row[:1] + [cell[:160] for cell in row[1:]]
                  for row in rows if any(name in row[0].casefold() for name in
                      ('draftkings', 'fanduel', 'betmgm', 'kalshi', 'polymarket'))][:8]}
    try:
        offers, rejected = parse(html, fixture, url, now, diagnostics=samples)
        result.update(accepted_offers=len(offers), rejected_cells=rejected,
                      rejection_samples=samples, parser_error=None)
    except Exception as exc:
        result.update(accepted_offers=0, parser_error=(type(exc).__name__ + ': ' + str(exc))[:300])
    return result


def main():
    now = dt.datetime.now(dt.timezone.utc)
    report = {'started_at_utc': now.isoformat(), 'execution_ok': False, 'betting_release': False,
              'scope': 'One current fixture; at most one request per source, no retries. '
                       'Transport success is not successful import, source completeness or model validation.'}
    try:
        paper = json.loads(Path('reports/paper_latest.json').read_text())
        index = json.loads(Path('reports/chat_index.json').read_text())
        fixture, url = select_fixture(paper, index, now)
        report['fixture'] = {k: fixture[k] for k in ('game_id', 'home', 'away', 'start_time_utc')}
        report['source_generated_at_utc'] = paper['generated_at_utc']
        date = stamp(fixture['start_time_utc']).astimezone(ZoneInfo('America/New_York')).strftime('%Y%m%d')
        for source, address, timeout in [('covers', url, 10), ('espn', BASE + date, 20)]:
            try:
                text, metadata = fetch(address, timeout)
                report[source] = dict(metadata, retrieval_ok=True)
                if source == 'covers':
                    report[source]['analysis'] = summarize_covers(text, fixture, url, now)
                else:
                    payload = json.loads(text)
                    report[source]['analysis'] = summarize_espn(payload, fixture, now)
                    from daily_review import collect
                    def replay(requested):
                        if requested != address:
                            raise ValueError('Unexpected collector URL; no extra request allowed')
                        return payload
                    offers, errors = collect(dict(paper, forecasts=[fixture]), now, loader=replay)
                    report[source]['collector_offer_count'] = len(offers)
                    report[source]['collector_errors'] = errors
            except Exception as exc:
                report.setdefault(source, {})['error'] = (type(exc).__name__ + ': ' + str(exc))[:300]
        report['execution_ok'] = all(report.get(s, {}).get('retrieval_ok') is True
            and 'error' not in report[s] for s in ('covers', 'espn'))
    except Exception as exc:
        report['error'] = (type(exc).__name__ + ': ' + str(exc))[:300]
    OUTPUT.parent.mkdir(exist_ok=True, parents=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
