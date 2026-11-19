"""Diagnostic groups for archived winner probabilities; never a betting release."""
import math


def selection_profile(records, summarize):
    records = list(records)
    for row in records:
        p, won = row['p'], row['won']
        if isinstance(p, bool) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError('Invalid archived probability')
        if isinstance(won, bool) or won not in (0, 1):
            raise ValueError('Invalid archived winner outcome')
    def favorite_p(row):
        return max(row['p'], 1 - row['p'])
    eligible = [r for r in records if favorite_p(r) >= .65]
    bands = []
    for lo, hi in [(.65, .70), (.70, .75), (.75, .80), (.80, 1.0)]:
        selected = [r for r in eligible if lo <= favorite_p(r) < hi
                    or (hi == 1.0 and favorite_p(r) == 1.0)]
        stats = summarize(selected, favorite=True)
        bands.append(dict(stats, lo=lo, hi=hi, upper_inclusive=(hi == 1.0)))
    return {'schema': 'probability-selection-profile-v1',
            'scope': 'Model-favorite winner events only; not handicaps, totals, actual picks or ROI',
            'probability_source': 'Archived experimental model probabilities; not bookmaker prices',
            'minimum_probability': .65, 'preferred_range': [.70, .75],
            'games_scored': len(records), 'games_below_profile': len(records) - len(eligible),
            'selected': summarize(eligible, favorite=True), 'bands': bands,
            'selection_rule': 'One model-favorite side per previously scored game; no outcome-based selection',
            'betting_release': False, 'calibration_validated': False,
            'limitations': ['Observed group hit rates are not individual prediction guarantees.',
                            'The preferred display band is [0.70, 0.75); larger probabilities remain included.',
                            'Subgroup intervals do not include model uncertainty or game dependence.',
                            'Profile thresholds were chosen after some archived outcomes were inspected; this regrouping is diagnostic, not an untouched policy test.',
                            'No automatic release at any sample size or observed hit rate.']}
