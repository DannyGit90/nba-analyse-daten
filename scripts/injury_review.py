"""Official NBA personnel evidence, isolated from model and recommendation gates."""
import datetime as dt
import hashlib
import io
import json
import os
import re
import unicodedata
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
UTC = dt.timezone.utc
TEAMS = dict(zip(('ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS').split(),
    ('Atlanta Hawks|Boston Celtics|Brooklyn Nets|Charlotte Hornets|Chicago Bulls|Cleveland Cavaliers|Dallas Mavericks|Denver Nuggets|Detroit Pistons|Golden State Warriors|Houston Rockets|Indiana Pacers|LA Clippers|Los Angeles Lakers|Memphis Grizzlies|Miami Heat|Milwaukee Bucks|Minnesota Timberwolves|New Orleans Pelicans|New York Knicks|Oklahoma City Thunder|Orlando Magic|Philadelphia 76ers|Phoenix Suns|Portland Trail Blazers|Sacramento Kings|San Antonio Spurs|Toronto Raptors|Utah Jazz|Washington Wizards').split('|')))
NAMES = {v:k for k,v in TEAMS.items()}
NAMES['Los Angeles Clippers'] = 'LAC'
ABBR = '(?:' + '|'.join(TEAMS) + ')'
TOKEN = re.compile(r'\d{2}/\d{2}/\d{4}|' + ABBR + '@' + ABBR + '|' + '|'.join(re.escape(n) for n in sorted(NAMES, key=len, reverse=True)))
PDF = re.compile(r'^/referee/injury/Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf$')


HEADER = re.compile(r'Injury\s*Report:\s*(\d{2}/\d{2}/(?:\d{4}|\d{2}))\s*(\d{1,2}:\d{2})\s*([AP]M)', re.I)
HOSTS = {'official.nba.com', 'ak-static.cms.nba.com', 'www.nba.com', 'nba.com'}


def normalize_text(text):
    text = unicodedata.normalize('NFKC', text).translate(dict.fromkeys(map(ord, '\u200b\u200c\u200d\ufeff')))
    for phrase in sorted(list(NAMES) + ['Injury Report', 'NOT YET SUBMITTED'], key=len, reverse=True):
        pattern = r'\s*'.join(re.escape(word) for word in phrase.split())
        text = re.sub(pattern, lambda m: phrase, text, flags=re.I)
    return text


def report_time(text):
    values = set()
    for date, clock, ampm in HEADER.findall(normalize_text(text)):
        fmt = '%m/%d/%Y' if len(date.rsplit('/', 1)[1]) == 4 else '%m/%d/%y'
        values.add(dt.datetime.strptime(date+' '+clock+' '+ampm.upper(), fmt+' %I:%M %p').replace(tzinfo=ET).astimezone(UTC))
    if len(values) != 1:
        raise ValueError('Report header missing or conflicting')
    return values.pop()


def check_response_url(url):
    u = urlparse(url)
    if u.scheme != 'https' or u.hostname not in HOSTS or u.username is not None or u.password is not None or u.port not in (None, 443):
        raise ValueError('Rejected response target: '+u.scheme+'://'+str(u.hostname))


class OfficialRedirects(HTTPRedirectHandler):
    max_redirections = 3
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_response_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def stamp(s):
    t = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timezone missing')
    return t


def published(url):
    u = urlparse(url)
    m = PDF.fullmatch(u.path)
    if u.scheme != 'https' or u.netloc != 'ak-static.cms.nba.com' or not m or u.query:
        raise ValueError('Not an official timestamped PDF')
    t = dt.datetime.strptime(' '.join(m.groups()), '%Y-%m-%d %I %M %p').replace(tzinfo=ET)
    if t.replace(fold=0).utcoffset() != t.replace(fold=1).utcoffset():
        raise ValueError('Ambiguous report timezone')
    return t.astimezone(UTC)


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.urls.extend(v for k,v in attrs if k == 'href' and v)


def candidates(html, now):
    p = Links(); p.feed(html)
    indexed_urls = {urljoin('https://ak-static.cms.nba.com', unescape(u)) for u in p.urls}
    urls = set(indexed_urls)
    rounded = now.astimezone(UTC).replace(second=0, microsecond=0)
    rounded -= dt.timedelta(minutes=rounded.minute % 15)
    for n in range(3):
        t = (rounded - dt.timedelta(minutes=15*n)).astimezone(ET)
        urls.add('https://ak-static.cms.nba.com/referee/injury/Injury-Report_' + t.strftime('%Y-%m-%d_%I_%M%p') + '.pdf')
    valid = {}
    for url in urls:
        url = urljoin('https://ak-static.cms.nba.com', unescape(url))
        try:
            t = published(url)
            if t <= now:
                valid[url] = t
        except ValueError:
            pass
    indexed = sorted((u for u in valid if u in indexed_urls), key=valid.get, reverse=True)[:1]
    recent = sorted(valid, key=valid.get, reverse=True)[:3]
    return sorted(set(recent + indexed), key=valid.get, reverse=True)


def download(url):
    check_response_url(url)
    with build_opener(OfficialRedirects()).open(Request(url, headers={'User-Agent':'nba-research/1.0'}), timeout=15) as r:
        check_response_url(r.geturl())
        body = r.read(4000001)
    if len(body) > 4000000:
        raise ValueError('Response too large')
    return body


def pdf_text(body):
    if not body.startswith(b'%PDF-'):
        raise ValueError('Not a PDF response')
    from pypdf import PdfReader
    pages = PdfReader(io.BytesIO(body)).pages
    if not 1 <= len(pages) <= 30:
        raise ValueError('Unexpected page count')
    text = '\n'.join(p.extract_text() or '' for p in pages)
    if not text.strip():
        raise ValueError('No extractable report text')
    return normalize_text(text)


def sections(text):
    text = HEADER.sub('', normalize_text(text))
    text = re.sub(r'Page\s*\d{1,2}\s*of\s*\d{1,2}?(?=\s*(?:\d{2}/\d{2}/\d{4}|\d{1,2}:\d{2}|[A-Za-z]|$))', '', text, flags=re.I)
    text = re.sub(r'Game\s*Date\s*Game\s*Time\s*Matchup\s*Team\s*Player\s*Name\s*Current\s*Status\s*Reason', '', text, flags=re.I)
    tokens = list(TOKEN.finditer(text))
    day, pair, out = None, None, {}
    for i, token in enumerate(tokens):
        value = token.group()
        if re.fullmatch(r'\d{2}/\d{2}/\d{4}', value):
            day = dt.datetime.strptime(value, '%m/%d/%Y').date().isoformat(); pair = None
        elif '@' in value:
            pair = value.split('@')
        elif day and pair and NAMES[value] in pair:
            raw = text[token.end():tokens[i+1].start() if i+1 < len(tokens) else len(text)].strip()
            key = (day, pair[0], pair[1], NAMES[value])
            raw = re.sub(r'\d{1,2}:\d{2}\s*\(ET\)\s*$', '', raw).strip()
            flat = re.sub(r'\s+', ' ', raw).strip()
            state = ('not_submitted' if flat == 'NOT YET SUBMITTED' else
                     'reported_raw' if ',' in raw and re.search(r'(?<![A-Z])(Out|Questionable|Doubtful|Probable|Available)(?![a-z])', raw)
                     and 'NOT YET SUBMITTED' not in raw else 'parse_unresolved')
            if key in out:
                state = 'parse_unresolved'
            out[key] = {'game_date_et':day, 'away':pair[0], 'home':pair[1], 'team':NAMES[value],
                        'status':state, 'raw_text':raw, 'player_level_assessment_complete':False}
    if not out:
        raise ValueError('No dated team/matchup sections found')
    return list(out.values())


def collect(now, loader=download, extractor=pdf_text):
    season = now.year if now.month >= 7 else now.year-1
    index = f'https://official.nba.com/nba-injury-report-{season}-{str(season+1)[2:]}-season/'
    attempts = []
    try:
        html = loader(index).decode('utf-8')
    except Exception as exc:
        html = ''; attempts.append({'source':index, 'error':type(exc).__name__, 'detail':str(exc)[:160]})
    for url in candidates(html, now):
        text = None
        try:
            body = loader(url); text = extractor(body)
            actual = report_time(text)
            if actual != published(url) or actual > now:
                raise ValueError('Report header/date mismatch')
            parts = sections(text)
            return {'schema':'official-personnel-v1', 'checked_at_utc':now.isoformat(), 'source':url,
                'source_published_at_utc':actual.isoformat(), 'retrieved_at_utc':now.isoformat(),
                'pdf_sha256':hashlib.sha256(body).hexdigest(), 'index_source':index,
                'status':'captured_raw' if now-actual <= dt.timedelta(hours=8) else 'stale',
                'freshness_note':'Eight hours is an operational ceiling, not a medical or statistical guarantee.',
                'attempts':attempts, 'sections':parts, 'betting_release':False}
        except Exception as exc:
            item = {'source':url, 'error':type(exc).__name__, 'detail':str(exc)[:160]}
            if text is not None:
                item['text_preview_ascii'] = ascii(text[:320])
            attempts.append(item)
    return {'schema':'official-personnel-v1', 'checked_at_utc':now.isoformat(), 'status':'unavailable',
            'attempts':attempts, 'sections':[], 'betting_release':False}


def render(payload):
    lines = ['# Automatischer offizieller Personalstand', '', 'Pruefzeit UTC: ' + payload['checked_at_utc'],
        'Erfassung: ' + payload['status'], 'Keine Personalkorrektur, Empfehlung oder Wettfreigabe.', '']
    lines += ['Tagesbericht ergaenzt: ' + str(payload.get('daily_report_appended', 'nicht geprueft')), '']
    if payload.get('append_error_detail'):
        lines += ['Tagesanhang-Fehler: ' + escape(payload['append_error_detail']), '']
    if payload.get('error'):
        lines += ['Fehler: ' + escape(payload['error']), '']
    if payload.get('previous_evidence_retained'):
        lines += ['[Letzter gesicherter Stand, nicht als neuer Abruf zu verstehen](last_good.json)', '']
    if payload.get('source'):
        lines += ['Quelle: ' + payload['source'], 'Berichtszeit UTC: ' + payload['source_published_at_utc'], '']
    if payload.get('attempts'):
        lines += ['## Abrufdiagnostik', '', '<pre>'+escape(json.dumps(payload['attempts'], ensure_ascii=True, indent=2))+'</pre>', '']
    for s in payload['sections']:
        lines += ['## ' + ' '.join((s['game_date_et'], s['away']+'@'+s['home'], s['team'])),
                  'Quellenstatus: ' + s['status'], '', '<pre>' + escape(s['raw_text']) + '</pre>', '']
    return '\n'.join(lines)


def append_daily(root, payload, now):
    root = Path(root)
    paper = json.loads((root/'paper_latest.json').read_text())
    source_time = stamp(paper['generated_at_utc'])
    if not now-dt.timedelta(hours=8) <= source_time <= now:
        raise ValueError('Base report stale or future')
    latest = root/'daily/latest.md'
    body = latest.read_text()
    match = re.match(r'# NBA-Tagesbericht (\d{4}-\d{2}-\d{2})', body)
    created = re.findall(r'^Bericht erstellt: (\S+) \(Europe/Berlin\)\.$', body, flags=re.M)
    if len(created) > 1 or ('Bericht erstellt:' in body and not created):
        raise ValueError('Invalid report creation metadata')
    anchor = stamp(created[0]) if created else source_time
    if not source_time <= anchor <= now:
        raise ValueError('Report creation time inconsistent with source or clock')
    if not match or match[1] != anchor.astimezone(ZoneInfo('Europe/Berlin')).date().isoformat():
        raise ValueError('Report date does not match its bound timestamp')
    archived = root/'daily'/(match[1]+'.md')
    if archived.read_text() != body or 'Quellstand UTC: '+paper['generated_at_utc']+'.' not in body:
        raise ValueError('Base report snapshot mismatch')
    rows = {(s['game_date_et'],s['away'],s['home'],s['team']):s for s in payload['sections']}
    extra = ['## Automatischer Personalstand', '',
        'Separater Abruf UTC: ' + payload['checked_at_utc'] + '; Quellenstatus: ' + payload['status'] + '.',
        'Berichtszeit UTC: ' + payload.get('source_published_at_utc', 'unbekannt') + '.',
        'Ergaenzt den bestehenden Berichtsstand; keine neue Prognose- oder Preispruefung.',
        ('Berichtsabschnitte eingelesen; Teamzuordnung siehe Tabelle. Spielerbezogene Bewertung offen.'
         if payload['status'] == 'captured_raw' else
         'Keine frische erfolgreiche Personalzuordnung. Der Quellenfehler ist keine Aussage ueber die Teamgesundheit.'),
        '[Personalbelege und Quellzeit](../injury/latest.md) | [Maschinenlesbare Belege](../injury/latest.json)', '',
        '| Begegnung | Auswaertsteam | Heimteam |', '|---|---|---|']
    for f in paper.get('forecasts', []):
        day = stamp(f['start_time_utc']).astimezone(ET).date().isoformat()
        states = [rows.get((day,f['away'],f['home'],f[side]),{}).get('status','not_in_report') for side in ('away','home')]
        if payload['status'] != 'captured_raw':
            states = ['source_'+payload['status']]*2
        extra.append('| '+' | '.join([f['away']+' bei '+f['home']]+states)+' |')
    extra += ['', 'not_submitted bedeutet nicht eingereicht, nicht gesund. reported_raw bedeutet nur Quelltext zugeordnet.',
              'Fehlende, alte oder nicht eindeutig zuordenbare Personalbelege sperren keine unabhaengige Quotenfassung.', '']
    result = body.split('\n## Automatischer Personalstand\n')[0].rstrip()+'\n\n'+'\n'.join(extra)
    latest.write_text(result); archived.write_text(result)


def main():
    root = Path('reports'); folder = root/'injury'; folder.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(UTC)
    try:
        if os.environ.get('INJURY_TESTS_OK') != 'success':
            raise ValueError('Personnel tests not successful')
        payload = collect(now)
        previous = folder/'last_good.json'
        if previous.exists() and payload.get('source_published_at_utc'):
            old = json.loads(previous.read_text())
            if stamp(payload['source_published_at_utc']) < stamp(old['source_published_at_utc']):
                raise ValueError('Source timestamp regressed; previous evidence retained separately')
    except Exception as exc:
        payload = {'schema':'official-personnel-v1','checked_at_utc':now.isoformat(),'status':'unavailable',
                   'error':str(exc)[:200],'sections':[],'betting_release':False}
    payload['previous_evidence_retained'] = (folder/'last_good.json').exists()
    try:
        append_daily(root, payload, now)
        payload['daily_report_appended'] = True
    except Exception as exc:
        payload['daily_report_appended'] = False; payload['append_error'] = type(exc).__name__
        payload['append_error_detail'] = str(exc)[:200]
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)+'\n'
    (folder/'latest.json').write_text(encoded)
    (folder/'latest.md').write_text(render(payload))
    if payload['status'] == 'captured_raw':
        (folder/'last_good.json').write_text(encoded)
    raise SystemExit(0 if payload['status'] == 'captured_raw' and payload['daily_report_appended'] else 1)


if __name__ == '__main__':
    main()
