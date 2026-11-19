"""One-page fetch diagnostic. Does not import offers or change betting gates."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from covers_review import Document, download

URL = 'https://www.covers.com/sport/basketball/nba/matchup/388756/odds'
OUTPUT = Path('reports/covers_fetch_probe.json')


def settings_hints(html):
    patterns = [
        ('select', r'<select\b[^>]*>.*?</select>'),
        ('odds_control', r'<[^>]*(?:odds[-_ ]?(?:settings|format)|oddsSettings|oddsFormat)[^>]*>'),
        ('location_control', r'<(?:select|input|button|a)\b[^>]*(?:country|region)[^>]*>'),
        ('script_reference', r'<script\b[^>]*\bsrc\s*=\s*[^>]+>'),
        ('provider_control', r'<(?:select|input|button|a)\b[^>]*(?:sportsbook|prediction)[^>]*>')]
    result = {'items': [], 'limited': False,
              'note': 'Public HTML hints only; not a verified switch. No links followed or scripts executed.'}
    for kind, pattern in patterns:
        matches = list(re.finditer(pattern, html, re.I | re.S))
        if kind == 'script_reference':
            matches.sort(key=lambda m: not any(k in m[0].lower() for k in ('odds', 'matchup', 'sport')))
        if len(matches) > 2:
            result['limited'] = True
        for match in matches[:2]:
            item = {'kind': kind, 'html_repr': ascii(match[0])[:240]}
            result['items'].append(item)
            if len(json.dumps(result, ensure_ascii=True).encode()) > 2400:
                result['items'].pop()
                result['limited'] = True
    return result


def summarize(html):
    doc = Document()
    doc.feed(html)
    report = {'title': doc.title[:180], 'sha256_utf8': hashlib.sha256(html.encode('utf-8')).hexdigest(),
              'table_blocks_seen': 0, 'tables': [], 'named_provider_rows': [], 'limited': False,
              'settings_hints': settings_hints(html),
              'note': 'Sampled table text before offer filters; not accepted odds or a saved earlier response.'}
    headings, block = [], None
    for kind, value in doc.events + [('table_end', None)]:
        if kind == 'heading':
            headings = (headings + [ascii(value)[:100]])[-3:]
        elif kind == 'row':
            if value and any(name in value[0].casefold() for name in ('draftkings', 'fanduel', 'betmgm')):
                if len(report['named_provider_rows']) < 6:
                    report['named_provider_rows'].append({'block_index': report['table_blocks_seen'],
                        'cell_count': len(value), 'cells': [ascii(x)[:140] for x in value[:4]]})
                else:
                    report['limited'] = True
            if block is None:
                block = {'headings': list(headings), 'row_count': 0, 'sample_rows': []}
            block['row_count'] += 1
            if len(block['sample_rows']) < 4:
                block['sample_rows'].append({'cell_count': len(value),
                                            'cells': [ascii(x)[:140] for x in value[:4]]})
        elif kind == 'table_end':
            if block is not None:
                if len(report['tables']) < 24:
                    report['tables'].append(dict(block, block_index=report['table_blocks_seen']))
                else:
                    report['limited'] = True
            block = None
            report['table_blocks_seen'] += 1
    report['table_blocks_seen'] -= 1
    while len(json.dumps(report, ensure_ascii=True, indent=2).encode('utf-8')) > 9000:
        for key in ('tables', 'named_provider_rows'):
            if report[key]:
                report[key].pop()
                break
        else:
            report['settings_hints']['items'].pop()
        report['limited'] = True
    return report


def main():
    report = {'source': URL, 'fetch_started_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'execution_ok': False, 'betting_release': False,
              'fetch_method': 'covers_review.download; one request, no retries'}
    try:
        html = download(URL)
        report['retrieved_at_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        report.update(summarize(html))
        report['execution_ok'] = True
    except Exception as exc:
        report['error'] = (type(exc).__name__ + ': ' + str(exc))[:300]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
