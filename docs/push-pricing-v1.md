# Integer-line push pricing, phase 1

Status: tested calculation library, NOT connected to live scoring. No wagering release.

## Scope and safety

- Existing season-prior10-paper-v1 forecasts, half-point calculations, archives and live report schemas are unchanged.
- This package supplies the three-outcome calculation core and CI tests. It does not remove the current integer-line gate or mark any existing reference computed.
- Quarter lines are unsupported. Half lines remain with the existing calculator.
- The integration of the new fields into scoring, ordering, normalization and the independent report auditor is a separate required step. Until then, this library must not be injected into the current two-outcome schema.

## Probability inputs

empirical_integer_probabilities accepts at least 200 explicitly discrete model outcomes: final full-game totals or home margins including overtime. Totals must be nonnegative integers; overtime home margins must be nonzero integers. Home and away handicap signs are selection-specific.

Do not measure a push by equality between a continuous prediction-plus-residual and an integer line: that would typically produce zero mass for the wrong reason.

residual_total_probabilities provides an explicitly NEW, UNVALIDATED experimental total model: nearest-integer bins of point plus residual. At integer total L the push bin lies between L-0.5 and L+0.5. Half-integer boundaries within absolute tolerance 1e-12 cause an error instead of silently choosing a tie convention. Negative or non-finite projected totals cause an error; there is no tail clipping. This bin mass is a model assumption, NOT an observed or calibrated push frequency. It must keep its own method ID. No continuous-residual rounding adapter is supplied for margins; supplying coherent discrete margin outcomes remains necessary.

## Cash single-bet mathematics

Let w, r and l be unconditional win, push and loss probabilities, summing to one. Let q be decimal odds. A push returns the cash stake and has zero net profit.

- Net EV per unit stake = w*(q-1)-l.
- Fair decimal price = (w+l)/w when w>0.
- Conditional win probability given no push = w/(w+l), when w+l>0.
- Break-even unconditional win probability = (w+l)/q.
- Break-even conditional win probability = 1/q when w+l>0.

For r=0 these reduce to the existing two-outcome formulas. Reject any w, r, l values that do not sum to one rather than normalizing silently. If all outcomes push, EV is zero and no meaningful fair price or conditional win probability exists. If w=0 and l>0, no finite fair price exists.

For example, synthetic w=.45, r=.15, l=.40 at q=2 gives EV=.05, NOT the two-outcome shortcut w*q-1=-.10. These numbers are a unit-test example, not an NBA prediction.

## Rule gate and provenance

price_reference requires an explicitly verified bookmaker AND jurisdiction, full-game scope, overtime inclusion, matching market, cash-stake refund on push, an HTTPS rules source and a timezone-aware verification timestamp no later than the calculation snapshot. It checks supplied metadata, not the truth of an external rulebook. The caller must establish that the rules apply to the specific offer; a URL or bookmaker name alone is insufficient.

Official example consulted: Fanatics Pennsylvania house rules, https://sportsbook.fanatics.com/legal/pa/house-rules/ . This jurisdiction-specific document is not blanket verification for Covers references, other jurisdictions or other bookmakers. No rules registry or automatic verification flag is added by this package.

All outputs retain probability_validation=unvalidated, betting_release=false and recommendation=null. The output field names distinguish unconditional win, push, conditional win and EV per stake; do not silently substitute conditional probability into p_experimental or use w*q-1 when r>0.

## Required before live activation

1. Match applicable settlement evidence to actual offers and retain its provenance.
2. Match model/distribution timestamps, protocol and method IDs; assess the experimental total binning separately from calibration claims.
3. Integrate push-aware fields and ordering consistently into scoring, normalization and independent auditing, preserving half-line behavior.
4. Run a complete live acceptance check. Only then may supported integer references change calculation status. No automatic recommendations or real-money authorization follow from that status.
