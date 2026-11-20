"""Separate technical progress from assessment; never authorize a recommendation."""
import datetime as dt
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

SCHEMA = 'pipeline-readiness-v1'
SIDES = {'moneyline': {'home', 'away'}, 'spread': {'home', 'away'}, 'total': {'over', 'under'}}


def blob(value):
    return (json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def save(path, value, limit=10000):
    body = blob(value)
    if len(body) > limit:
        raise ValueError('Readiness report exceeds byte budget')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def header(paper):
    return {k: paper[k] for k in ('generated_at_utc', 'protocol')}


def numeric_fields(value, prefix='', depth=0):
    result = {}
    if depth > 8:
        return result
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in ('link', 'links', 'logos', 'logo', 'team', 'provider'):
                continue
            result.update(numeric_fields(item, prefix + ('.' if prefix else '') + key, depth + 1))
            if len(result) >= 60:
                break
    elif type(value) in (int, float) and math.isfinite(value):
        result[prefix] = value
    elif isinstance(value, str) and len(value) <= 48:
        try:
            if math.isfinite(float(value)):
                result[prefix] = value
        except ValueError:
            pass
    return dict(list(result.items())[:60])


def collect_espn(paper, now, loader=None, root=Path('reports'), collector=None):
    if collector is None:
        from daily_review import collect as collector
    samples, capture_errors = [], []
    def capture(url):
        if loader is None:
            with urlopen(Request(url, headers={'User-Agent': 'nba-research/1.0'}), timeout=20) as r:
                body = r.read(4000001)
            if len(body) > 4000000:
                raise ValueError('Response exceeds size limit')
            payload = json.loads(body)
        else:
            payload = loader(url)
        try:
            for event in payload.get('events', []):
                for c in event.get('competitions', []):
                    if len(samples) >= 3:
                        break
                    aliases = {'GS': 'GSW', 'NY': 'NYK', 'NO': 'NOP', 'SA': 'SAS', 'UTAH': 'UTA', 'WSH': 'WAS'}
                    teams = {x.get('homeAway'): aliases.get(x.get('team', {}).get('abbreviation'),
                             x.get('team', {}).get('abbreviation')) for x in c.get('competitors', [])}
                    date = c.get('date', event.get('date'))
                    state = c.get('status', event.get('status', {})).get('type', {}).get('state')
                    for f in paper['forecasts']:
                        try:
                            start = dt.datetime.fromisoformat(f['start_time_utc'].replace('Z', '+00:00'))
                            match = (date and dt.datetime.fromisoformat(date.replace('Z', '+00:00')) == start
                                     and start > now and state == 'pre'
                                     and (teams.get('home'), teams.get('away')) == (f['home'], f['away']))
                        except (ValueError, TypeError):
                            match = False
                        if match:
                            for odds in c.get('odds', [])[:1]:
                                samples.append({'game_id': f['game_id'], 'source': url,
                                    'provider': str(odds.get('provider', {}).get('name', ''))[:64],
                                    'numeric_fields': numeric_fields(odds)})
                            break
        except Exception as exc:
            if not capture_errors:
                capture_errors.append({'source': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard', 'error': 'ESPN field inspection failed: ' + str(exc)[:120]})
        return payload
    offers, errors = collector(paper, now, loader=capture)
    report = dict(header(paper), schema='espn-observed-price-fields-v1',
        observed_at_utc=now.isoformat(), betting_release=False, samples=samples,
        scope='At most three matching pregame blocks, at most 60 numeric leaves each; same production responses, no extra requests. Not parsed offers or validated prices.')
    try:
        save(root / 'espn_price_fields.json', report, limit=20000)
    except Exception as exc:
        capture_errors.append({'source': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard', 'error': 'ESPN field report not saved: ' + str(exc)[:120]})
    return offers, list(errors) + capture_errors


def build_readiness(paper, index, rows, evaluation=None):
    h = header(paper)
    if any(index.get(k) != h[k] for k in h):
        raise ValueError('Readiness snapshot mismatch')
    if paper.get('execution_ok') is not True or index.get('execution_ok') is not True:
        raise ValueError('Upstream execution failed')
    if paper.get('money_betting_released') is not False or index.get('betting_release') is not False:
        raise ValueError('Readiness cannot alter a release')
    if len(rows) != index['actual_offer_count'] or sum(
            r.get('calculation_status') == 'computed_reference_only' for r in rows) != index['computed_offer_count']:
        raise ValueError('Readiness counts mismatch')
    ids = [f['game_id'] for f in paper['forecasts']]
    if len(ids) != len(set(ids)) or set(ids) != {f['game_id'] for f in index['fixtures']}:
        raise ValueError('Readiness fixture mismatch')
    if any(r.get('game_id') not in ids or r.get('market') not in SIDES
           or r.get('side') not in SIDES[r['market']] or r.get('betting_release') is not False
           or r.get('recommendation') is not None for r in rows):
        raise ValueError('Unsupported or released raw offer')
    fixtures = []
    for gid in ids:
        markets = {}
        for market, expected in SIDES.items():
            selected = [r for r in rows if r['game_id'] == gid and r['market'] == market]
            sides = {r['side'] for r in selected}
            markets[market] = {'offers': len(selected),
                'capture': 'missing' if not sides else 'both_sides_observed' if sides == expected else 'partial_sides',
                'computed': sum(r.get('calculation_status') == 'computed_reference_only' for r in selected),
                'uncomputed': sum(r.get('calculation_status') != 'computed_reference_only' for r in selected),
                'assessment': 'not_recorded_by_pipeline'}
        fixtures.append({'game_id': gid, 'markets': markets})
    e = evaluation if isinstance(evaluation, dict) else {}
    matching = e.get('protocol') == paper['protocol'] and e.get('execution_ok') is True
    profile = e.get('favorite_selection_profile', {}) if matching else {}
    return dict(h, schema=SCHEMA, execution_ok=True, betting_release=False,
        scope='Observed normalized references, not full market coverage or completed qualitative research.',
        assessment_note='No chat decisions imported or overwritten. Retain separately documented completed assessments; missing pipeline record is not a rejection or proof of no value.',
        fixtures=fixtures, recommendation_count=None,
        model_evidence={'evaluation_status': 'diagnostic_only' if matching else 'missing_or_mismatched',
            'checked_at_utc': e.get('checked_at_utc') if matching else None,
            'games_scored': e.get('games_scored') if matching else None,
            'favorite_calibration_validated': profile.get('calibration_validated') if matching else None,
            'not_verified_by_this_report': ['independent_line_probability_method',
                'out_of_sample_calibration_by_market_and_selection_policy',
                'timestamped_roster_scenario_method', 'offer_bound_settlement_rules'],
            'automatic_release': False,
            'sample_size_alone_can_authorize_release': False})


def main(root=Path('reports')):
    def read(path):
        return json.loads((root / path).read_text())
    try:
        paper, index = read('paper_latest.json'), read('chat_index.json')
        rows = []
        for f in index['fixtures']:
            gid = f['game_id']
            import re
            if not re.fullmatch(r'002\d{7}', gid) or f['context_path'] != f'reports/chat/{gid}.json':
                raise ValueError('Unsafe context path')
            ctx = read(f'chat/{gid}.json')
            if any(ctx.get(k) != paper[k] for k in header(paper)) or ctx['fixture']['game_id'] != gid:
                raise ValueError('Context snapshot mismatch')
            seen = set()
            for path in ctx['market_pages']:
                if path in seen or not re.fullmatch(r'reports/chat/' + gid + r'-markets-\d+\.json', path):
                    raise ValueError('Unsafe or duplicate market path')
                seen.add(path)
                page = read(path.removeprefix('reports/'))
                if any(page.get(k) != paper[k] for k in header(paper)) or any(r.get('game_id') != gid for r in page['offers']):
                    raise ValueError('Market snapshot mismatch')
                rows.extend(page['offers'])
        evaluation = read('paper_evaluation.json') if (root / 'paper_evaluation.json').exists() else None
        report = build_readiness(paper, index, rows, evaluation)
        probe = root / 'espn_price_fields.json'
        if probe.exists():
            observed = read('espn_price_fields.json')
            if all(observed.get(k) == paper[k] for k in header(paper)):
                report['observed_espn_fields_path'] = 'reports/espn_price_fields.json'
        index['pipeline_readiness_path'] = 'reports/pipeline_readiness.json'
        if len(blob(index)) > 10000:
            raise ValueError('Index exceeds byte budget')
        save(root / 'pipeline_readiness.json', report)
        save(root / 'chat_index.json', index)
    except Exception as exc:
        save(root / 'pipeline_readiness.json', {'schema': SCHEMA, 'execution_ok': False,
            'betting_release': False, 'error': str(exc)[:300]})
        raise


if __name__ == '__main__':
    main()
