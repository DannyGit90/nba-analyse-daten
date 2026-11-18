import copy
import json
import math
import re
from collections import Counter
from pathlib import Path

SCHEMA = 'market-reporting-v1'
BOOKS = ['BetMGM', 'bet365', 'DraftKings', 'FanDuel', 'Fanatics Sportsbook',
         'BetRivers', 'Caesars', 'theScore Bet', 'Hard Rock Bet']


def bookmaker(name):
    clean = ' '.join(str(name).split())
    for alias, canonical in [(x, x) for x in BOOKS] + [('Caesars Odds', 'Caesars')]:
        if re.fullmatch(r'(?:' + re.escape(alias) + r'\s*)+', clean, flags=re.I):
            return canonical
    return clean


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def number(value, default=-1e100):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else default


def priority(row):
    computed = row.get('calculation_status') == 'computed_reference_only'
    p, ev = number(row.get('p_experimental')), number(row.get('paper_ev'))
    valid = computed and 0 <= p <= 1 and ev > -1e99
    bucket = 2 if valid and ev > 0 else 1 if valid else 0
    return bucket, p if valid else -1, ev if valid else -1e100


def prepare(rows):
    unique = {}
    for original in rows:
        row = copy.deepcopy(original)
        if row.get('betting_release') is not False or row.get('recommendation') is not None:
            raise ValueError('Raw-reference stage cannot overwrite a release or recommendation')
        market, side = row.get('market'), row.get('side')
        if market not in ('moneyline', 'spread', 'total') or side not in (
                ('over', 'under') if market == 'total' else ('home', 'away')):
            raise ValueError('Unsupported market or side')
        q = number(row.get('odds'))
        if q <= 1:
            raise ValueError('Invalid decimal odds')
        row['odds'] = q
        if market != 'moneyline':
            line = number(row.get('line'))
            if line <= -1e99 or (market == 'total' and line <= 0):
                raise ValueError('Invalid line')
            row['line'] = 0.0 if line == 0 else line
        elif row.get('line') is not None:
            raise ValueError('Moneyline cannot carry a handicap')
        if row.get('calculation_status') == 'computed_reference_only':
            p = number(row.get('p_experimental'))
            if not 0 <= p <= 1:
                raise ValueError('Invalid computed probability')
            expected = {'paper_ev': p * q - 1, 'break_even': 1 / q}
            if p > 0:
                expected['paper_fair_odds'] = 1 / p
            elif row.get('paper_fair_odds') is not None:
                raise ValueError('Zero probability requires an undefined fair price')
            if any(not math.isclose(number(row.get(k)), value, rel_tol=1e-10, abs_tol=1e-10)
                   for k, value in expected.items()):
                raise ValueError('Stored arithmetic does not match probability and price')
        raw = row.get('bookmaker_raw', row.get('bookmaker', ''))
        row['bookmaker_raw'] = raw
        row['bookmaker'] = bookmaker(row.get('bookmaker', ''))
        if not row['bookmaker']:
            raise ValueError('Empty bookmaker')
        key = tuple(json.dumps(row.get(k), sort_keys=True) for k in
                    ('game_id', 'market', 'side', 'line', 'odds', 'bookmaker',
                     'rules_verified', 'includes_overtime', 'region', 'settlement_rule', 'rules_source', 'market_scope', 'price_status'))
        proof = {k: row.get(k) for k in ('source', 'observed_at_utc', 'price_timestamp_utc', 'bookmaker_raw')}
        provenance = list(row.get('provenance', []))
        if proof not in provenance:
            provenance.append(proof)
        if key in unique:
            old = unique[key]
            fields = ('calculation_status', 'p_experimental', 'paper_ev', 'break_even', 'paper_fair_odds', 'reason')
            if any(old.get(k) != row.get(k) for k in fields):
                raise ValueError('Conflicting calculations for the same normalized offer')
            for item in provenance:
                if item not in old['provenance']:
                    old['provenance'].append(item)
            continue
        row['provenance'] = provenance
        row['priority_bucket'] = ('positive_paper_ev_unvalidated' if priority(row)[0] == 2
                                  else 'nonpositive_paper_ev' if priority(row)[0] == 1 else 'not_rankable')
        row['recommendation'] = None
        row['betting_release'] = False
        unique[key] = row
    return sorted(unique.values(), key=priority, reverse=True)


def coverage(rows):
    groups = {}
    for market in ('moneyline', 'spread', 'total'):
        items = [r for r in rows if r['market'] == market]
        lines = {}
        for side in sorted({r['side'] for r in items}):
            lines[side] = sorted({r['line'] for r in items if r['side'] == side and r.get('line') is not None})
        selections = {(r['side'], r.get('line')) for r in items}
        by_provider = {}
        for r in items:
            if r.get('line') is not None:
                by_provider.setdefault(r['bookmaker'], {}).setdefault(r['side'], set()).add(r['line'])
        by_provider = {book: {side: sorted(values) for side, values in sides.items()}
                       for book, sides in sorted(by_provider.items())}
        groups[market] = {'provider_lines': by_provider,
                          'same_provider_side_multiple_lines_observed': any(len(values) > 1 for sides in by_provider.values() for values in sides.values()),
                          'offers': len(items), 'providers': len({r['bookmaker'] for r in items}),
                          'selections': len(selections), 'lines_by_side': lines,
                          'computed': sum(r.get('calculation_status') == 'computed_reference_only' for r in items),
                          'uncomputed_reasons': dict(Counter(r.get('reason', 'unspecified') for r in items
                              if r.get('calculation_status') != 'computed_reference_only')),
                          'scope': 'observed_references_only', 'full_alternative_ladder_verified': False}
    return groups


def same_snapshot(obj, header):
    if any(obj.get(k) != header[k] for k in ('generated_at_utc', 'protocol')):
        raise ValueError('Snapshot mismatch')


def finalize(root=Path('reports')):
    def read(path):
        return json.loads((root / path).read_text())
    index, paper = read('chat_index.json'), read('paper_latest.json')
    if index.get('execution_ok') is not True or paper.get('execution_ok') is not True or paper.get('money_betting_released') is not False:
        raise ValueError('Upstream execution failed')
    header = {k: paper[k] for k in ('generated_at_utc', 'protocol')}
    same_snapshot(index, header)
    gids = [f['game_id'] for f in index['fixtures']]
    if len(set(gids)) != len(gids) or set(gids) != {f['game_id'] for f in paper['forecasts']}:
        raise ValueError('Invalid fixture sets')
    raw_rows, contexts = [], {}
    for fixture in index['fixtures']:
        gid = fixture['game_id']
        if not re.fullmatch(r'002\d{7}', gid) or fixture['context_path'] != f'reports/chat/{gid}.json':
            raise ValueError('Unsafe game or context path')
        context = read(f'chat/{gid}.json')
        same_snapshot(context, header)
        if context['fixture']['game_id'] != gid:
            raise ValueError('Context game mismatch')
        contexts[gid] = context
        seen = set()
        for path in context['market_pages']:
            if not re.fullmatch(r'reports/chat/' + gid + r'-markets-\d+\.json', path) or path in seen:
                raise ValueError('Unsafe or duplicate market page path')
            seen.add(path)
            page = read(path.removeprefix('reports/'))
            same_snapshot(page, header)
            if any(r.get('game_id') != gid for r in page['offers']):
                raise ValueError('Market page game mismatch')
            raw_rows.extend(page['offers'])
    if len(raw_rows) != index['actual_offer_count']:
        raise ValueError('Raw offer count does not match index')
    if sum(r.get('calculation_status') == 'computed_reference_only' for r in raw_rows) != index['computed_offer_count']:
        raise ValueError('Computed offer count does not match index')
    rows = prepare(raw_rows)
    manifest = dict(header, schema=SCHEMA, execution_ok=True, betting_release=False,
                    input_offer_count=len(raw_rows), unique_offer_count=len(rows),
                    duplicates_removed=len(raw_rows) - len(rows), fixtures=[],
                    ranking='Positive unvalidated paper-EV bucket first; probability descending, EV tie-breaker; not recommendations',
                    full_alternative_coverage_verified=False,
                    uncomputed_reasons=dict(Counter(r.get('reason', 'unspecified') for r in rows
                        if r.get('calculation_status') != 'computed_reference_only')))
    pending = {}
    for fixture in index['fixtures']:
        gid = fixture['game_id']
        selected = [r for r in rows if r['game_id'] == gid]
        context = copy.deepcopy(contexts[gid])
        context['market_pages'] = []
        group = coverage(selected)
        cov_path = f'chat/{gid}-coverage.json'
        pending[cov_path] = dict(header, schema=SCHEMA, game_id=gid, markets=group,
                                 full_alternative_ladder_verified=False, betting_release=False)
        batch = []
        pages = []
        for row in selected:
            candidate = dict(header, offers=batch + [row], betting_release=False)
            if batch and len(encoded(candidate)) > 10000:
                pages.append(batch)
                batch = []
            batch.append(row)
            if len(encoded(dict(header, offers=batch, betting_release=False))) > 10000:
                raise ValueError('A single offer exceeds the page limit')
        if batch:
            pages.append(batch)
        for n, batch in enumerate(pages):
            path = f'chat/{gid}-markets-{n}.json'
            pending[path] = dict(header, offers=batch, betting_release=False)
            context['market_pages'].append('reports/' + path)
        context['coverage_path'] = 'reports/' + cov_path
        pending[f'chat/{gid}.json'] = context
        fixture['offer_count'] = len(selected)
        fixture['coverage_path'] = 'reports/' + cov_path
        manifest['fixtures'].append({'game_id': gid, 'offers': len(selected), 'coverage_path': 'reports/' + cov_path,
                                    'market_counts': {m: group[m]['offers'] for m in group}})
    index['actual_offer_count'] = len(rows)
    index['computed_offer_count'] = sum(r.get('calculation_status') == 'computed_reference_only' for r in rows)
    index['market_reporting'] = {'schema': SCHEMA, 'coverage_path': 'reports/market_coverage.json',
                                 'duplicates_removed': manifest['duplicates_removed'],
                                 'ranking': manifest['ranking']}
    paper['research_extension'].update(actual_offer_count=index['actual_offer_count'],
                                       computed_offer_count=index['computed_offer_count'],
                                       market_coverage_path='reports/market_coverage.json')
    pending.update({'chat_index.json': index, 'paper_latest.json': paper, 'market_coverage.json': manifest})
    blobs = {path: encoded(obj) for path, obj in pending.items()}
    for path, body in blobs.items():
        if len(body) > (16000 if path == 'paper_latest.json' else 10000):
            raise ValueError('Report exceeds byte limit: ' + path)
    for path, body in blobs.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    return manifest


def main():
    root = Path('reports')
    try:
        finalize(root)
    except Exception as exc:
        root.mkdir(exist_ok=True)
        (root / 'market_coverage.json').write_bytes(encoded({'schema': SCHEMA, 'execution_ok': False,
                                                           'betting_release': False, 'error': str(exc)}))


if __name__ == '__main__':
    main()
