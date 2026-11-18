import copy
import datetime as dt
import json
import math
import re
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='
ALIASES = {'GS': 'GSW', 'NY': 'NYK', 'NO': 'NOP', 'SA': 'SAS', 'UTAH': 'UTA', 'WSH': 'WAS'}


def stamp(value):
    t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timezone required')
    return t


def american(value):
    if isinstance(value, bool):
        raise ValueError('Boolean odds')
    x = float(value)
    if not math.isfinite(x) or abs(x) < 100:
        raise ValueError('Invalid American odds')
    return 1 + (x / 100 if x > 0 else 100 / -x)


def team(value):
    return ALIASES.get(value, value)


def collect(paper, now, loader=None):
    if loader is None:
        def loader(url):
            request = Request(url, headers={'User-Agent': 'nba-research/1.0'})
            with urlopen(request, timeout=20) as response:
                body = response.read(4000001)
            if len(body) > 4000000:
                raise ValueError('Response exceeds size limit')
            return json.loads(body)
    dates = sorted({stamp(f['start_time_utc']).astimezone(ZoneInfo('America/New_York')).strftime('%Y%m%d')
                    for f in paper['forecasts']})
    offers, errors = [], []
    for date in dates[:3]:
        url = BASE + date
        try:
            payload = loader(url)
            for event in payload['events']:
                for c in event.get('competitions', []):
                    if c.get('status', event.get('status', {})).get('type', {}).get('state') != 'pre':
                        continue
                    competitors = {x['homeAway']: team(x['team']['abbreviation']) for x in c['competitors']}
                    matches = [f for f in paper['forecasts'] if f['home'] == competitors.get('home')
                               and f['away'] == competitors.get('away')
                               and stamp(f['start_time_utc']) == stamp(c.get('date', event['date']))]
                    if len(matches) != 1 or stamp(matches[0]['start_time_utc']) <= now:
                        continue
                    f = matches[0]
                    for odds in c.get('odds', []):
                        provider = odds.get('provider', {}).get('name')
                        if not isinstance(provider, str) or not provider.strip() or provider.strip().lower() in ('unknown', 'n/a', 'none'):
                            continue
                        base = {'game_id': f['game_id'], 'bookmaker': provider, 'source': url,
                                'observed_at_utc': now.isoformat(), 'price_timestamp_utc': None,
                                'price_status': 'indirect_reference_time_unknown',
                                'rules_verified': False, 'betting_release': False}
                        def add(market, side, price, line=None):
                            try:
                                q = american(price)
                                if (market != 'moneyline' and line is None) or (line is not None and not math.isfinite(float(line))):
                                    return
                                offers.append(dict(base, market=market, side=side, odds=q, line=line))
                            except (ValueError, TypeError):
                                pass
                        for side in ('home', 'away'):
                            add('moneyline', side, odds.get(side + 'TeamOdds', {}).get('moneyLine'))
                        detail = re.fullmatch(r'([A-Z]{2,4})\s+([+-]?\d+(?:\.\d+)?)', odds.get('details', '') or '')
                        if detail and team(detail[1]) in (f['home'], f['away']):
                            hline = float(detail[2]) * (1 if team(detail[1]) == f['home'] else -1)
                            for side, line in [('home', hline), ('away', -hline)]:
                                add('spread', side, odds.get(side + 'TeamOdds', {}).get('spreadOdds'), line)
                        add('total', 'over', odds.get('overOdds'), odds.get('overUnder'))
                        add('total', 'under', odds.get('underOdds'), odds.get('overUnder'))
        except Exception as exc:
            errors.append({'source': url, 'error': str(exc)[:300]})
    unique = {}
    for o in offers:
        unique.setdefault((o['game_id'], o['bookmaker'], o['market'], o['side'], o['line'], o['odds']), o)
    return list(unique.values()), errors


def score(paper, distribution, offers, now):
    from research_packet import half_point_probability, paper_price
    fixtures = {f['game_id']: f for f in paper['forecasts']}
    rows = []
    for offer in offers:
        row = dict(offer)
        row['recommendation'] = None
        try:
            f = fixtures[offer['game_id']]
            observed = stamp(offer['observed_at_utc'])
            if not now - dt.timedelta(hours=2) <= observed <= now:
                raise ValueError('Retrieval stale or future; not evidence of price freshness')
            if stamp(f['start_time_utc']) <= now or stamp(paper['generated_at_utc']) >= stamp(f['start_time_utc']):
                raise ValueError('Not a pregame snapshot')
            if not now - dt.timedelta(hours=8) <= stamp(paper['generated_at_utc']) <= now:
                raise ValueError('Model report stale or future')
            if paper.get('execution_ok') is not True or paper.get('completed_schedule_games_missing_from_logs'):
                raise ValueError('Paper data gate failed')
            if not offer.get('bookmaker') or not str(offer.get('source', '')).startswith('https://'):
                raise ValueError('Missing provider or source')
            market, side = offer['market'], offer['side']
            if market == 'moneyline' and side in ('home', 'away'):
                probability = f['p_' + side + '_experimental']
            elif market in ('spread', 'total'):
                if distribution.get('available') is not True or any(
                        distribution.get(k) != paper.get(k) for k in ('generated_at_utc', 'protocol')):
                    raise ValueError('Distribution unavailable or mismatched')
                point = f['home_margin_point' if market == 'spread' else 'total_point']
                errors = distribution['margin_residuals' if market == 'spread' else 'total_residuals']
                probability = half_point_probability(point, errors, market, side, offer['line'])
            else:
                raise ValueError('Unsupported market or side')
            row.update(paper_price(probability, offer['odds']))
            row['calculation_status'] = 'computed_reference_only'
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            row.update(calculation_status='not_computed', reason=str(exc))
        rows.append(row)
    return rows


def encode(payload):
    return (json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def publish(paper, packet, rows, errors, root=Path('reports')):
    if packet.get('execution_ok') is not True or paper.get('execution_ok') is not True:
        raise ValueError('Source execution failed')
    for k in ('generated_at_utc', 'protocol'):
        if paper.get(k) != packet.get(k):
            raise ValueError('Research snapshot mismatch')
    contexts = {f['game_id']: f for f in packet['fixtures']}
    if len(contexts) != len(packet['fixtures']) or set(contexts) != {f['game_id'] for f in paper['forecasts']}:
        raise ValueError('Fixture set mismatch')
    header = {k: paper[k] for k in ('generated_at_utc', 'protocol')}
    index = dict(header, execution_ok=True, betting_release=False, fixtures=[], source_errors=errors,
                 actual_offer_count=len(rows), computed_offer_count=sum(r['calculation_status'] == 'computed_reference_only' for r in rows),
                 alternatives_coverage='Only actual returned lines; no full alternative ladder guaranteed',
                 analysis_status='Paper references only; injury, rotation, rules and qualitative review still required')
    pending = {}
    slim = copy.deepcopy(paper)
    for f in slim['forecasts']:
        gid = f['game_id']
        if not re.fullmatch(r'002\d{7}', gid):
            raise ValueError('Unsafe or unsupported NBA game ID')
        path = f'chat/{gid}.json'
        item = dict(header, fixture=contexts[gid], market_pages=[])
        selected = [r for r in rows if r['game_id'] == gid]
        selected.sort(key=lambda r: r.get('paper_ev', -1e100), reverse=True)
        for offset in range(0, len(selected), 5):
            page = f'chat/{gid}-markets-{offset // 5}.json'
            pending[page] = dict(header, offers=selected[offset:offset + 5], betting_release=False)
            item['market_pages'].append('reports/' + page)
        if not selected:
            item['market_status'] = 'no_usable_offers_received_not_a_negative_betting_decision'
        pending[path] = item
        index['fixtures'].append({'game_id': gid, 'away': f['away'], 'home': f['home'],
                                  'context_path': 'reports/' + path, 'offer_count': len(selected)})
        f.pop('home_context', None)
        f.pop('away_context', None)
        f['context_path'] = 'reports/' + path
        for side in ('home', 'away'):
            ctx = contexts[gid][side + '_context']
            f[side + '_summary'] = {'n': ctx['season_games'], 'last10_n': ctx['last10_games'],
                                   'rest_days': ctx['rest_days_uncapped'],
                                   'season': [round(ctx['season_mean_per_game'][k], 3) for k in ('off_rating', 'def_rating', 'pace')],
                                   'last10': [round(ctx['last10_mean_per_game'][k], 3) for k in ('off_rating', 'def_rating', 'pace')]}
    slim['research_extension'] = {'schema': 'chat-pages-v1', 'index_path': 'reports/chat_index.json',
                                  'markets_linked': bool(rows), 'automatic_recommendations': False,
                                  'summary_columns': ['off_rating', 'def_rating', 'pace'],
                                  'summary_method': 'Unweighted per-game means, rounded to 3 decimals; not opponent adjusted',
                                  'actual_offer_count': index['actual_offer_count'],
                                  'computed_offer_count': index['computed_offer_count']}
    pending['chat_index.json'] = index
    pending['paper_latest.json'] = slim
    rendered = {path: encode(value) for path, value in pending.items()}
    for path, body in rendered.items():
        limit = 16000 if path == 'paper_latest.json' else 10000
        if len(body) > limit:
            raise ValueError('Chat file exceeds byte budget: ' + path)
    for path, body in rendered.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    return index


def main():
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
