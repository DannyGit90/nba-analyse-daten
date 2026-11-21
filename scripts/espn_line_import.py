"""Normalize observed ESPN close spread/total fields; never use opening prices."""
import copy
import math
import re
from pathlib import Path
from daily_review import american, stamp, team, collect as legacy_collect
from pipeline_readiness import collect_espn


def field(obj, *keys):
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean line')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Nonfinite line')
    return result


def normalize(block, fixture):
    out, proofs, issues = copy.deepcopy(block), [], []
    for market, group, sides in [('spread', 'pointSpread', ('home', 'away')),
                                  ('total', 'total', ('over', 'under'))]:
        closes = {s: field(block, group, s, 'close') for s in sides}
        if not any(field(closes[s], 'odds') is not None for s in sides):
            continue
        try:
            prices = {s: field(closes[s], 'odds') for s in sides}
            for price in prices.values():
                if price is not None:
                    american(price)
            if market == 'spread':
                lines = {s: number(field(closes[s], 'line')) for s in sides}
                if not math.isclose(sum(lines.values()), 0, rel_tol=0, abs_tol=1e-9):
                    raise ValueError('Spread sides are not opposite lines')
                detail = re.fullmatch(r'([A-Z]{2,4})\s+([+-]?\d+(?:\.\d+)?)', block.get('details', '') or '')
                old_prices = {s: field(block, s + 'TeamOdds', 'spreadOdds') for s in sides}
                if any(p is not None for p in old_prices.values()):
                    if not detail or team(detail[1]) not in (fixture['home'], fixture['away']):
                        raise ValueError('Legacy spread price has no comparable line')
                    old_home = float(detail[2]) * (1 if team(detail[1]) == fixture['home'] else -1)
                    if not math.isclose(old_home, lines['home'], rel_tol=0, abs_tol=1e-9):
                        raise ValueError('Conflicting legacy and close spread lines')
            else:
                total = number(block.get('overUnder'))
                if total <= 0:
                    raise ValueError('Nonpositive total')
                lines = {s: total for s in sides}
                old_prices = {s: block.get(s + 'Odds') for s in sides}
                for side in sides:
                    raw_line = field(closes[side], 'line')
                    if raw_line is not None:
                        text = str(raw_line).strip().lower()
                        if text[:1] in ('o', 'u'):
                            if text[0] != side[0]:
                                raise ValueError('Total side prefix mismatch')
                            text = text[1:]
                        if not math.isclose(number(text), total, rel_tol=0, abs_tol=1e-9):
                            raise ValueError('Close total line differs from overUnder')
            for side in sides:
                if old_prices[side] is not None and prices[side] is not None and not math.isclose(
                        american(old_prices[side]), american(prices[side]), rel_tol=0, abs_tol=1e-12):
                    raise ValueError('Conflicting legacy and close prices')
            if market == 'spread':
                out['details'] = fixture['home'] + ' ' + format(lines['home'], '+.12g')
                for side in sides:
                    out.setdefault(side + 'TeamOdds', {})['spreadOdds'] = prices[side]
            else:
                for side in sides:
                    out[side + 'Odds'] = prices[side]
            for side in sides:
                if prices[side] is not None:
                    proofs.append((market, side, lines[side], american(prices[side]),
                        group + '.' + side + '.close.odds',
                        group + '.' + side + '.close.line' if market == 'spread' or
                        field(closes[side], 'line') is not None else 'overUnder'))
        except (ValueError, TypeError, AttributeError) as exc:
            if market == 'spread':
                for side in sides:
                    old = out.get(side + 'TeamOdds')
                    if isinstance(old, dict):
                        old.pop('spreadOdds', None)
            else:
                out.pop('overOdds', None)
                out.pop('underOdds', None)
            issues.append((market, str(exc)[:140]))
    return out, proofs, issues


def collect_lines(paper, now, loader):
    proofs, diagnostics = {}, []
    omitted, used = 0, 0
    def adapt(url):
        nonlocal omitted, used
        payload = copy.deepcopy(loader(url))
        for event in payload.get('events', []):
            for c in event.get('competitions', []):
                if c.get('status', event.get('status', {})).get('type', {}).get('state') != 'pre':
                    continue
                teams = {x['homeAway']: team(x['team']['abbreviation']) for x in c.get('competitors', [])}
                matches = [f for f in paper['forecasts'] if (f['home'], f['away']) ==
                    (teams.get('home'), teams.get('away')) and stamp(f['start_time_utc']) ==
                    stamp(c.get('date', event['date'])) and stamp(f['start_time_utc']) > now]
                if len(matches) != 1:
                    continue
                f = matches[0]
                blocks = []
                for block in c.get('odds', []):
                    normalized, evidence, issues = normalize(block, f)
                    blocks.append(normalized)
                    book = field(block, 'provider', 'name')
                    for market, side, line, price, price_field, line_field in evidence:
                        proofs[(url, f['game_id'], book, market, side, line, price)] = (price_field, line_field)
                    for market, error in issues:
                        record = {'source': url, 'game_id': f['game_id'], 'market': market, 'error': error}
                        import json
                        size = len(json.dumps(record))
                        if used + size <= 768:
                            diagnostics.append(record)
                            used += size
                        else:
                            omitted += 1
                c['odds'] = blocks
        return payload
    rows, errors = legacy_collect(paper, now, loader=adapt)
    for row in rows:
        key = tuple(row.get(k) for k in ('source', 'game_id', 'bookmaker', 'market', 'side', 'line', 'odds'))
        if key in proofs:
            row['price_field'], row['line_field'] = proofs[key]
            row['source_price_label'] = 'close'
    if omitted:
        diagnostics.append({'source': 'https://site.api.espn.com',
                            'error': 'Additional line-schema diagnostics omitted', 'omitted_count': omitted})
    return rows, list(errors) + diagnostics


def collect(paper, now, loader=None, root=Path('reports')):
    return collect_espn(paper, now, loader=loader, root=root, collector=collect_lines)
