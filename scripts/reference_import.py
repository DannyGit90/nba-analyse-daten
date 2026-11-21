"""Combine reference sources without changing pricing or recommendation gates."""
import datetime as dt
import json
from pathlib import Path

ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
SELECTIONS = {('moneyline', 'home'), ('moneyline', 'away'),
              ('spread', 'home'), ('spread', 'away'),
              ('total', 'over'), ('total', 'under')}


def collect_references(paper, now, primary=None, secondary=None):
    if primary is None:
        from covers_review import collect as primary
    if secondary is None:
        from espn_line_import import collect as secondary
    forecasts = [f for f in paper['forecasts']
                 if dt.datetime.fromisoformat(f['start_time_utc'].replace('Z', '+00:00')) > now]
    if not forecasts:
        return [], []
    active = dict(paper, forecasts=forecasts)
    expected = {(f['game_id'], market, side) for f in forecasts for market, side in SELECTIONS}
    try:
        offers, errors = primary(active, now)
    except Exception as exc:
        offers, errors = [], [{'source': 'https://www.covers.com',
                              'error': (type(exc).__name__ + ': ' + str(exc))[:200]}]
    offers, errors = list(offers), list(errors)
    covered = {(r['game_id'], r['market'], r['side']) for r in offers}
    missing = expected - covered
    if missing:
        ids = {key[0] for key in missing}
        fallback_paper = dict(active, forecasts=[f for f in forecasts if f['game_id'] in ids])
        try:
            rows, fallback_errors = secondary(fallback_paper, now)
        except Exception as exc:
            rows, fallback_errors = [], [{'source': ESPN,
                'error': (type(exc).__name__ + ': ' + str(exc))[:200]}]
        errors.extend(fallback_errors)
        additions = [r for r in rows if (r['game_id'], r['market'], r['side']) in missing]
        additions = list({tuple(r.get(k) for k in (
            'game_id', 'bookmaker', 'market', 'side', 'line', 'odds', 'source')): r
            for r in additions}.values())
        offers.extend(additions)
        remaining = missing - {(r['game_id'], r['market'], r['side']) for r in additions}
        diagnostic = {'source': ESPN, 'status': 'fallback_attempted',
                      'missing_selection_groups_before': len(missing),
                      'fallback_offers_added': len(additions),
                      'missing_selection_groups_after': len(remaining),
                      'note': 'Selection groups only; not full line or bookmaker coverage.'}
        if not additions:
            diagnostic['error'] = 'No matching fallback reference offers collected'
        errors.append(diagnostic)
    unique = {}
    for row in offers:
        key = tuple(row.get(k) for k in ('game_id', 'bookmaker', 'market', 'side', 'line', 'odds', 'source'))
        unique.setdefault(key, row)
    return list(unique.values()), errors


def main():
    from daily_review import score, publish, encode
    root = Path('reports')
    try:
        paper = json.loads((root / 'paper_latest.json').read_text())
        packet = json.loads((root / 'research_packet.json').read_text())
        distribution = json.loads((root / 'paper_distribution.json').read_text())
        now = dt.datetime.now(dt.timezone.utc)
        offers, errors = collect_references(paper, now)
        rows = score(paper, distribution, offers, now)
        publish(paper, packet, rows, errors, root)
    except Exception as exc:
        root.mkdir(exist_ok=True)
        (root / 'chat_index.json').write_bytes(encode({
            'execution_ok': False, 'betting_release': False, 'error': str(exc)}))


if __name__ == '__main__':
    main()
