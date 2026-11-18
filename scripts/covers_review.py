import datetime as dt
import json
import math
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = 'https://www.covers.com'
ALIASES = {'BK': 'BKN', 'GS': 'GSW', 'NO': 'NOP', 'NY': 'NYK', 'SA': 'SAS', 'PHO': 'PHX', 'UTAH': 'UTA'}


def stamp(s):
    t = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timezone required')
    return t


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.events, self.links, self.title = [], set(), ''
        self.heading, self.cell, self.row = None, None, None
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'title':
            self.in_title = True
        if tag in ('h1', 'h2', 'h3', 'h4'):
            self.heading = []
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th') and self.row is not None:
            self.cell = []
        if tag == 'img' and self.cell is not None:
            self.cell.append(a.get('alt', ''))
        if tag == 'a' and a.get('href'):
            m = re.search(r'/sport/basketball/nba/matchup/(\d+)(?:/odds)?(?:[/?#]|$)', a['href'])
            if m:
                self.links.add(ROOT + '/sport/basketball/nba/matchup/' + m[1] + '/odds')

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.heading is not None:
            self.heading.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'table':
            self.events.append(('table_end', None))
        if tag == 'title':
            self.in_title = False
        if tag in ('h1', 'h2', 'h3', 'h4') and self.heading is not None:
            self.events.append(('heading', ' '.join(self.heading).strip()))
            self.heading = None
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(self.cell).strip())
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.events.append(('row', self.row))
            self.row = None


def parse(html, fixture, url, now):
    doc = Document()
    doc.feed(html)
    date = stamp(fixture['start_time_utc']).astimezone(ZoneInfo('America/New_York'))
    title = re.sub(r'\s+', ' ', doc.title)
    patterns = [f"{date.strftime('%B')} {date.day}, {date.year}", f"{date.strftime('%b')} {date.day}, {date.year}"]
    if not any(x.lower() in title.lower() for x in patterns):
        raise ValueError('Page title does not confirm the expected game date')
    market, columns, teams_seen = None, None, False
    offers, rejected = [], 0
    for kind, value in doc.events:
        if kind == 'table_end':
            if columns is not None:
                market, columns = None, None
            continue
        if kind == 'heading':
            key = value.strip().lower()
            mapping = {'spread': 'spread', 'total': 'total', 'moneyline': 'moneyline',
                       'alternate spread': 'spread', 'alternative spread': 'spread',
                       'alternate total': 'total', 'alternative total': 'total'}
            if key in mapping:
                market, columns = mapping[key], None
            elif key not in ('odds comparison', 'compare odds'):
                market, columns = None, None
            continue
        if market is None or len(value) != 3:
            continue
        clean = [re.sub(r'\s+', ' ', x).strip() for x in value]
        if clean[0].replace(' ', '').upper() == 'ALLBOOKS':
            names = [ALIASES.get(x, x) for x in clean[1:]]
            if market == 'total':
                columns = ['over', 'under'] if [x.upper() for x in names] == ['OVER', 'UNDER'] else None
            elif set(names) == {fixture['home'], fixture['away']}:
                teams_seen = True
                columns = ['home' if x == fixture['home'] else 'away' for x in names]
            else:
                columns = None
            continue
        if columns is None:
            continue
        book = re.sub(r'\s+logo\b', '', clean[0], flags=re.I).strip()
        if not book or book == '-':
            continue
        for side, cell in zip(columns, clean[1:]):
            if cell == '-':
                continue
            cell = cell.replace('−', '-')
            pattern = r'([+-]\d+(?:\.\d+)?)' if market == 'moneyline' else r'([ou]?[+-]?\d+(?:\.\d+)?)\s+([+-]\d+(?:\.\d+)?)'
            m = re.fullmatch(pattern, cell, flags=re.I)
            if not m:
                rejected += 1
                continue
            line = None if market == 'moneyline' else float(re.sub(r'^[ou]', '', m[1], flags=re.I))
            a = float(m[1] if market == 'moneyline' else m[2])
            if not math.isfinite(a) or abs(a) < 100:
                rejected += 1
                continue
            if market == 'total' and ((side == 'over' and not m[1].lower().startswith('o')) or (side == 'under' and not m[1].lower().startswith('u'))):
                rejected += 1
                continue
            offers.append({'game_id': fixture['game_id'], 'market': market, 'side': side,
                           'line': line, 'odds': 1 + (a / 100 if a > 0 else 100 / -a),
                           'bookmaker': book, 'source': url, 'observed_at_utc': now.isoformat(),
                           'price_timestamp_utc': None, 'price_status': 'indirect_reference_time_unknown',
                           'rules_verified': False, 'betting_release': False})
    if not teams_seen:
        raise ValueError('No comparison header confirms both teams')
    unique = {(o['bookmaker'], o['market'], o['side'], o['line'], o['odds']): o for o in offers}
    return list(unique.values()), rejected


def download(url):
    with urlopen(Request(url, headers={'User-Agent': 'nba-research/1.0'}), timeout=10) as r:
        body = r.read(4000001)
    if len(body) > 4000000:
        raise ValueError('Response too large')
    return body.decode('utf-8')


def collect(paper, now, loader=download):
    offers, errors, urls = [], [], set()
    try:
        doc = Document()
        doc.feed(loader(ROOT + '/sport/basketball/nba/odds'))
        urls.update(doc.links)
    except Exception as exc:
        errors.append({'source': ROOT, 'error': str(exc)[:200]})
    dates = {stamp(f['start_time_utc']).astimezone(ZoneInfo('America/New_York')).strftime('%Y%m%d') for f in paper['forecasts']}
    seed = {ROOT + f'/sport/basketball/nba/matchup/{n}/odds' for n in range(388744, 388756)} if '20261118' in dates else set()
    ordered = sorted(seed) + sorted(urls - seed)
    if len(ordered) > 48:
        errors.append({'source': ROOT, 'error': 'Discovery budget: additional pages not fetched', 'remaining': len(ordered) - 48})
    if not ordered:
        errors.append({'source': ROOT, 'error': 'No matchup links discovered'})
    for url in ordered[:48]:
        try:
            html = loader(url)
            matched = False
            for f in paper['forecasts']:
                if stamp(f['start_time_utc']) <= now:
                    continue
                try:
                    rows, rejected = parse(html, f, url, now)
                except ValueError:
                    continue
                offers.extend(rows)
                matched = True
                if rejected:
                    errors.append({'source': url, 'game_id': f['game_id'], 'rejected_cells': rejected})
                break
            if not matched:
                errors.append({'source': url, 'error': 'Date/team/table format did not match a fixture'})
        except Exception as exc:
            errors.append({'source': url, 'error': str(exc)[:200]})
    unique = {(o['game_id'], o['bookmaker'], o['market'], o['side'], o['line'], o['odds']): o for o in offers}
    if not unique:
        errors.append({'source': ROOT, 'error': 'No valid Covers reference offers collected'})
    return list(unique.values()), errors


def main():
    from daily_review import score, publish, encode
    root = Path('reports')
    try:
        paper = json.loads((root / 'paper_latest.json').read_text())
        packet = json.loads((root / 'research_packet.json').read_text())
        distribution = json.loads((root / 'paper_distribution.json').read_text())
        now = dt.datetime.now(dt.timezone.utc)
        offers, errors = collect(paper, now)
        rows = score(paper, distribution, offers, now)
        publish(paper, packet, rows, errors, root)
    except Exception as exc:
        root.mkdir(exist_ok=True)
        (root / 'chat_index.json').write_bytes(encode({'execution_ok': False, 'betting_release': False, 'error': str(exc)}))


if __name__ == '__main__':
    main()
