import json
import math
import re
from collections import Counter
from pathlib import Path

BRANDS = ['BetMGM', 'bet365', 'DraftKings', 'FanDuel', 'Fanatics Sportsbook',
          'BetRivers', 'Caesars', 'theScore Bet', 'Hard Rock Bet']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(raw):
    text = ' '.join(str(raw).split())
    for alias, name in [(b, b) for b in BRANDS] + [('Caesars Odds', 'Caesars')]:
        unit, rest, count = alias.casefold(), text.casefold(), 0
        while rest.startswith(unit):
            rest = rest[len(unit):].lstrip()
            count += 1
        if count and not rest:
            return name
    return text


def audit(root=Path('reports')):
    used = set()
    header = {}
    def read(path, limit=10000):
        require(path not in used, 'Duplicate active file reference: ' + path)
        used.add(path)
        body = (root / path).read_bytes()
        require(len(body) <= limit, 'Byte limit: ' + path)
        obj = json.loads(body)
        if header:
            require(all(obj.get(k) == v for k, v in header.items()), 'Snapshot mismatch: ' + path)
        return obj
    paper = read('paper_latest.json', 16000)
    header.update({k: paper[k] for k in ('generated_at_utc', 'protocol')})
    index, manifest = read('chat_index.json'), read('market_coverage.json')
    require(all(x.get('execution_ok') is True for x in (paper, index, manifest)), 'Upstream execution failed')
    require(paper.get('money_betting_released') is False, 'Unexpected model release')
    require(index.get('betting_release') is False and manifest.get('betting_release') is False, 'Unexpected release')
    require(manifest.get('full_alternative_coverage_verified') is False, 'Unsupported completeness claim')
    ids = [f['game_id'] for f in index['fixtures']]
    model_ids = [f['game_id'] for f in paper['forecasts']]
    manifest_ids = [f['game_id'] for f in manifest['fixtures']]
    require(len(ids) == len(set(ids)) == len(model_ids) == len(set(model_ids)) == len(manifest_ids) == len(set(manifest_ids)), 'Duplicate or missing fixtures')
    require(set(ids) == set(model_ids) == set(manifest_ids), 'Fixture sets differ')
    total, computed, reasons, results = 0, 0, Counter(), []
    for f in index['fixtures']:
        gid = f['game_id']
        require(re.fullmatch(r'002\d{7}', gid) is not None, 'Unsafe game ID')
        require(f['context_path'] == f'reports/chat/{gid}.json', 'Context path mismatch')
        context = read(f'chat/{gid}.json')
        require(context['fixture']['game_id'] == gid, 'Context game mismatch')
        cov_path = f'reports/chat/{gid}-coverage.json'
        require(f['coverage_path'] == context['coverage_path'] == cov_path, 'Coverage link mismatch')
        cov = read(cov_path.removeprefix('reports/'))
        require(cov['game_id'] == gid and cov.get('betting_release') is False, 'Coverage identity/release mismatch')
        require(cov.get('full_alternative_ladder_verified') is False, 'Unverified ladder claim')
        rows = []
        for path in context['market_pages']:
            require(re.fullmatch(r'reports/chat/' + gid + r'-markets-\d+\.json', path) is not None, 'Unsafe market path')
            page = read(path.removeprefix('reports/'))
            require(page.get('betting_release') is False, 'Market page released')
            rows.extend(page['offers'])
        require(len(rows) == f['offer_count'], 'Fixture offer count mismatch')
        prior, keys = None, set()
        for r in rows:
            require(r['game_id'] == gid, 'Foreign offer in page')
            require(r.get('betting_release') is False and r.get('recommendation') is None, 'Unexpected recommendation')
            require(r['bookmaker'] == canonical(r['bookmaker_raw']), 'Provider normalization mismatch')
            proof = {k: r.get(k) for k in ('source', 'observed_at_utc', 'price_timestamp_utc', 'bookmaker_raw')}
            require(proof in r.get('provenance', []), 'Original provenance missing')
            require(all(str(p.get('source', '')).startswith('https://') and p.get('observed_at_utc') for p in r['provenance']), 'Incomplete provenance')
            key = tuple(json.dumps(r.get(k), sort_keys=True) for k in ('game_id', 'market', 'side', 'line', 'odds', 'bookmaker', 'rules_verified', 'includes_overtime', 'region', 'settlement_rule', 'rules_source', 'market_scope', 'price_status'))
            require(key not in keys, 'Duplicate normalized offer')
            keys.add(key)
            market, side = r['market'], r['side']
            require(market in ('moneyline', 'spread', 'total'), 'Unknown market')
            require(side in (('over', 'under') if market == 'total' else ('home', 'away')), 'Unknown side')
            q = r['odds']
            require(type(q) in (int, float) and math.isfinite(q) and q > 1, 'Invalid odds')
            require(r.get('line') is None if market == 'moneyline' else type(r.get('line')) in (int, float) and math.isfinite(r['line']), 'Invalid market line')
            status = r.get('calculation_status')
            require(status in ('computed_reference_only', 'not_computed'), 'Unknown calculation status')
            if status == 'computed_reference_only':
                p, ev = r['p_experimental'], r['paper_ev']
                require(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1, 'Invalid probability')
                expected = {'paper_ev': p * q - 1, 'break_even': 1 / q}
                if p:
                    expected['paper_fair_odds'] = 1 / p
                else:
                    require(r.get('paper_fair_odds') is None, 'Zero probability fair price')
                require(all(type(r.get(k)) in (int, float) and math.isclose(r[k], v, rel_tol=1e-10, abs_tol=1e-10) for k, v in expected.items()), 'Arithmetic mismatch')
                rank = (2 if ev > 0 else 1, p, ev)
                bucket = 'positive_paper_ev_unvalidated' if ev > 0 else 'nonpositive_paper_ev'
                computed += 1
            else:
                require(isinstance(r.get('reason'), str) and bool(r['reason']), 'Missing calculation failure reason')
                reasons[r['reason']] += 1
                rank, bucket = (0, -1, -1e100), 'not_rankable'
            require(r['priority_bucket'] == bucket, 'Priority bucket mismatch')
            require(prior is None or prior >= rank, 'Probability/EV ordering mismatch')
            prior = rank
        for market in ('moneyline', 'spread', 'total'):
            subset = [r for r in rows if r['market'] == market]
            actual = cov['markets'][market]
            expected = {'offers': len(subset), 'providers': len({r['bookmaker'] for r in subset}),
                        'selections': len({(r['side'], r.get('line')) for r in subset}),
                        'computed': sum(r['calculation_status'] == 'computed_reference_only' for r in subset),
                        'uncomputed_reasons': dict(Counter(r['reason'] for r in subset if r['calculation_status'] == 'not_computed'))}
            expected['lines_by_side'] = {side: sorted({r['line'] for r in subset if r['side'] == side and r.get('line') is not None}) for side in sorted({r['side'] for r in subset})}
            provider_lines = {}
            for r in subset:
                if r.get('line') is not None:
                    provider_lines.setdefault(r['bookmaker'], {}).setdefault(r['side'], set()).add(r['line'])
            expected['provider_lines'] = {b: {s: sorted(v) for s, v in sides.items()} for b, sides in provider_lines.items()}
            expected['same_provider_side_multiple_lines_observed'] = any(len(v) > 1 for sides in provider_lines.values() for v in sides.values())
            require(all(actual.get(k) == v for k, v in expected.items()), 'Coverage differs from actual rows: ' + gid + '/' + market)
            require(actual.get('full_alternative_ladder_verified') is False and actual.get('scope') == 'observed_references_only', 'Incorrect coverage scope')
        m = next(x for x in manifest['fixtures'] if x['game_id'] == gid)
        require(m['offers'] == len(rows) and m['coverage_path'] == cov_path, 'Manifest fixture mismatch')
        require(m['market_counts'] == dict(Counter(r['market'] for r in rows)) or m['market_counts'] == {k: sum(r['market'] == k for r in rows) for k in ('moneyline', 'spread', 'total')}, 'Manifest market counts mismatch')
        total += len(rows)
        results.append({'game_id': gid, 'offers_checked': len(rows), 'active_pages': len(context['market_pages'])})
    require(total == index['actual_offer_count'] == manifest['unique_offer_count'], 'Global offer count mismatch')
    require(computed == index['computed_offer_count'], 'Global computed count mismatch')
    require(dict(reasons) == manifest['uncomputed_reasons'], 'Global failure reasons mismatch')
    require(0 <= manifest['duplicates_removed'] <= manifest['input_offer_count'] and manifest['input_offer_count'] - manifest['duplicates_removed'] == total, 'Duplicate accounting mismatch')
    require(paper['research_extension']['actual_offer_count'] == total and paper['research_extension']['computed_offer_count'] == computed, 'Paper extension counts mismatch')
    ignored = sorted(str(p.relative_to(root)) for p in (root / 'chat').glob('*-markets-*.json') if str(p.relative_to(root)) not in used)
    return dict(header, audit_schema='market-reporting-audit-v1', execution_ok=True, betting_release=False,
                fixtures_checked=len(ids), offers_checked=total, computed_checked=computed,
                not_computed_checked=total - computed, active_files_checked=len(used),
                unreferenced_market_pages_ignored=len(ignored), fixtures=results,
                scope='Published reference-report integrity only; not model validation, live-price verification or full source coverage')


def main():
    root = Path('reports')
    root.mkdir(exist_ok=True)
    try:
        report = audit(root)
    except Exception as exc:
        report = {'audit_schema': 'market-reporting-audit-v1', 'execution_ok': False,
                  'betting_release': False, 'error': str(exc)}
    (root / 'market_reporting_audit.json').write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
