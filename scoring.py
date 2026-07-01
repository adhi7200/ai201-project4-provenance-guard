"""Confidence scoring: combine the detection signals into a single decision.

Every signal emits P(AI) in [0, 1]. They are combined into a weighted ensemble
(see planning.md, Uncertainty representation and the Ensemble stretch feature):

  combined = weighted mean of the signal P(AI) values
  spread   = max(P(AI)) - min(P(AI)) across the signals

  spread <= SPREAD_GATE -> signals agree, verdict from the bands below
  spread  > SPREAD_GATE -> signals disagree, force uncertain

Bands are asymmetric so a tie favors the creator (a false positive, calling a
human's work AI, is worse than a false negative here):

  combined >= 0.70 and agree -> likely_ai
  combined <= 0.40            -> likely_human
  otherwise                  -> uncertain

Weights: GROQ (semantic) is heaviest because meaning is the hardest property to
fake; stylometry is a solid but gameable middle; compression is the noisiest cue
and gets the least say.
"""

DEFAULT_WEIGHTS = {"llm": 0.5, "stylo": 0.3, "compression": 0.2}

SPREAD_GATE = 0.40  # generalization of the old two-signal gap of 0.25
AI_BAR = 0.70
HUMAN_BAR = 0.40  # combined <= 0.40 means P(human) >= 0.60


def score(signals, weights=None):
    """Combine per-signal P(AI) values into a decision.

    signals: dict of {name: p_ai}. weights: dict of {name: weight}; defaults to
    DEFAULT_WEIGHTS, restricted to the signals actually provided (and renormalized).

    Returns a dict: combined (P(AI)), attribution, agree (bool),
    display_confidence (0..1), and spread.
    """
    if not signals:
        raise ValueError("at least one signal is required")

    weights = weights or DEFAULT_WEIGHTS
    used = {name: weights.get(name, 0.0) for name in signals}
    total_w = sum(used.values())
    if total_w == 0:
        # No configured weights for these signals; fall back to equal weighting.
        used = {name: 1.0 for name in signals}
        total_w = sum(used.values())

    values = list(signals.values())
    combined = sum(signals[name] * used[name] for name in signals) / total_w
    spread = max(values) - min(values)
    agree = spread <= SPREAD_GATE

    if not agree:
        attribution = "uncertain"
    elif combined >= AI_BAR:
        attribution = "likely_ai"
    elif combined <= HUMAN_BAR:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

    # Confidence shown to the reader is confidence in the stated verdict.
    if attribution == "likely_ai":
        display_confidence = combined
    elif attribution == "likely_human":
        display_confidence = 1 - combined
    else:
        # Uncertain: report the strength of the (insufficient) lean, so a near
        # coin-flip reads ~0.5 rather than a misleading high number.
        display_confidence = max(combined, 1 - combined)

    return {
        "combined": round(combined, 3),
        "attribution": attribution,
        "agree": agree,
        "display_confidence": round(display_confidence, 3),
        "spread": round(spread, 3),
    }
