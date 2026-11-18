import copy
import datetime as dt
import math
from numbers import Real

MIN_SAMPLES = 200


def number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError('Finite numeric value required; no booleans or numeric strings')
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError('Numeric value outside float range') from exc
    if not math.isfinite(result):
        raise ValueError('Non-finite numeric value')
    return result


def integer_line(market, side, line):
    line = number(line)
    if not line.is_integer():
        raise ValueError('Integer lines only; half/quarter lines are not handled here')
    if market == 'total' and side in ('over', 'under') and line > 0:
        return line
    if market == 'spread' and side in ('home', 'away'):
        return line
    raise ValueError('Unsupported market, side or line')


def empirical_integer_probabilities(samples, market, side, line):
    line = integer_line(market, side, line)
    values = [number(x) for x in samples]
    if len(values) < MIN_SAMPLES:
        raise ValueError('At least 200 discrete model outcomes required')
    if any(not x.is_integer() for x in values):
        raise ValueError('Discrete integer outcomes required; do not compare continuous residuals for equality')
    if market == 'total':
        if any(x < 0 for x in values):
            raise ValueError('Negative total outcome')
        margins = [(x - line) * (1 if side == 'over' else -1) for x in values]
    else:
        if any(x == 0 for x in values):
            raise ValueError('Full-game overtime home margins cannot be zero')
        margins = [(x if side == 'home' else -x) + line for x in values]
    if any(not math.isfinite(x) for x in margins):
        raise ValueError('Settlement margin exceeds finite numeric range')
    counts = {'win': sum(x > 0 for x in margins), 'push': sum(x == 0 for x in margins),
              'loss': sum(x < 0 for x in margins)}
    return {'market': market, 'side': side, 'line': line, 'sample_n': len(values), 'counts': counts,
            'p_win': counts['win'] / len(values), 'p_push': counts['push'] / len(values),
            'p_loss': counts['loss'] / len(values), 'method': 'empirical_integer_outcomes_v1',
            'probability_validation': 'unvalidated', 'betting_release': False}


def residual_total_probabilities(point, residuals, side, line):
    integer_line('total', side, line)
    point = number(point)
    samples = []
    for error in residuals:
        value = point + number(error)
        if not math.isfinite(value) or value < 0:
            raise ValueError('Non-finite or negative projected total; no tail clipping')
        fraction = value - math.floor(value)
        if math.isclose(fraction, .5, rel_tol=0, abs_tol=1e-12):
            raise ValueError('Half-integer rounding boundary requires review')
        samples.append(math.floor(value + .5))
    result = empirical_integer_probabilities(samples, 'total', side, line)
    result['method'] = 'experimental_total_residual_bins_v1'
    result['assumption'] = 'Nearest-integer total bins; a new unvalidated discretization, not an observed push frequency'
    return result


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('ISO timestamp string required')
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


def price_reference(outcomes, decimal_odds, rules, as_of_utc):
    integer_line(outcomes['market'], outcomes['side'], outcomes['line'])
    if rules.get('rules_verified') is not True:
        raise ValueError('Offer-specific settlement rules not verified')
    if (rules.get('market') != outcomes['market'] or rules.get('market_scope') != 'full_game'
            or rules.get('includes_overtime') is not True
            or rules.get('push_settlement') != 'cash_stake_refund'):
        raise ValueError('Full-game overtime cash-refund rule mismatch')
    for key in ('bookmaker', 'jurisdiction', 'rules_source', 'verified_at_utc'):
        if not isinstance(rules.get(key), str) or not rules[key].strip():
            raise ValueError('Missing rule provenance: ' + key)
    if not rules['rules_source'].startswith('https://'):
        raise ValueError('HTTPS rule source required')
    if timestamp(rules['verified_at_utc']) > timestamp(as_of_utc):
        raise ValueError('Rule verification is later than the calculation snapshot')
    if not isinstance(outcomes.get('method'), str) or not outcomes['method'].strip():
        raise ValueError('Probability method identity required')
    win, push, loss = [number(outcomes[k]) for k in ('p_win', 'p_push', 'p_loss')]
    q = number(decimal_odds)
    if any(not 0 <= x <= 1 for x in (win, push, loss)) or not math.isclose(win + push + loss, 1, rel_tol=0, abs_tol=1e-12):
        raise ValueError('Win/push/loss probabilities must sum to one; no automatic normalization')
    if q <= 1:
        raise ValueError('Decimal odds must exceed one')
    resolved = win + loss
    fair = resolved / win if win else None
    ev = win * (q - 1) - loss
    if not math.isfinite(ev) or (fair is not None and not math.isfinite(fair)):
        raise ValueError('Pricing exceeds finite numeric range')
    return {'market': outcomes['market'], 'side': outcomes['side'], 'line': float(outcomes['line']),
            'decimal_odds': q, 'p_win_unconditional': win, 'p_push': push, 'p_loss_unconditional': loss,
            'p_win_given_no_push': win / resolved if resolved else None,
            'break_even_p_win_unconditional': resolved / q,
            'break_even_p_win_given_no_push': 1 / q if resolved else None,
            'fair_decimal_odds': fair, 'ev_per_unit_stake': ev,
            'price_state': 'all_push' if not resolved else 'no_finite_fair_price' if not win else 'finite',
            'probability_method': outcomes['method'], 'probability_validation': 'unvalidated',
            'rules_context': copy.deepcopy(rules), 'calculated_as_of_utc': as_of_utc,
            'status': 'experimental_push_reference_only', 'recommendation': None, 'betting_release': False}


def price_offer_reference(outcomes, offer, rules, as_of_utc):
    """Match supplied metadata only; no online rule verification or live activation.

    Bookmaker labels must already be canonicalized by the caller; aliases are not guessed.
    """
    from urllib.parse import urlsplit
    if offer.get('rules_verified') is not True:
        raise ValueError('Offer settlement evidence is not verified')
    for key in ('game_id', 'bookmaker', 'jurisdiction', 'source', 'observed_at_utc'):
        if (not isinstance(offer.get(key), str) or not offer[key].strip()
                or offer[key].strip().casefold() in ('unknown', 'none', 'n/a', '-')):
            raise ValueError('Missing offer binding: ' + key)
    if offer['game_id'] != outcomes.get('game_id'):
        raise ValueError('Outcome game does not match offer')
    for key in ('market', 'side'):
        if offer.get(key) != outcomes.get(key):
            raise ValueError('Outcome selection does not match offer: ' + key)
    line = integer_line(offer.get('market'), offer.get('side'), offer.get('line'))
    if line != number(outcomes.get('line')):
        raise ValueError('Outcome line does not match offer')
    for key in ('bookmaker', 'jurisdiction'):
        value = rules.get(key)
        if not isinstance(value, str) or not value.strip() or ' '.join(value.split()).casefold() != ' '.join(offer[key].split()).casefold():
            raise ValueError('Rule does not match offer: ' + key)
    if offer.get('market_scope') != 'full_game' or offer.get('includes_overtime') is not True:
        raise ValueError('Offer full-game overtime scope is unverified')
    for value in (offer['source'], rules.get('rules_source')):
        if not isinstance(value, str):
            raise ValueError('Missing HTTPS binding source')
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username is not None or url.password is not None:
            raise ValueError('Invalid HTTPS binding source')
    if timestamp(offer['observed_at_utc']) > timestamp(as_of_utc):
        raise ValueError('Offer observation is later than the calculation snapshot')
    result = price_reference(outcomes, offer.get('odds'), rules, as_of_utc)
    result['offer_binding'] = copy.deepcopy({k: offer[k] for k in
        ('game_id', 'bookmaker', 'jurisdiction', 'market', 'side', 'line', 'odds', 'source', 'observed_at_utc')})
    result['offer_binding_check'] = 'supplied_metadata_only'
    return result
