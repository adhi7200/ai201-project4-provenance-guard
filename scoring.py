"""Confidence scoring: combine the two signals into a single decision.

Both signals emit P(AI) in [0, 1]. We combine them through an agreement gate
(see planning.md, Uncertainty representation):

  gap = |llm_score - stylo_score|
    gap <= 0.25  -> signals agree, combined = mean
    gap  > 0.25  -> signals disagree, force uncertain

Bands are asymmetric so a tie favors the creator (a false positive, calling a
human's work AI, is worse than a false negative here):

  combined >= 0.70 and agree -> likely_ai
  combined <= 0.40            -> likely_human
  otherwise                  -> uncertain
"""

AGREEMENT_GAP = 0.25
AI_BAR = 0.70
HUMAN_BAR = 0.40  # combined <= 0.40 means P(human) >= 0.60


def score(llm_score, stylo_score):
    """Combine the two P(AI) signals into a decision.

    Returns a dict: combined (P(AI)), attribution, agree (bool),
    and display_confidence (0..1, the confidence in the attribution shown).
    """
    gap = abs(llm_score - stylo_score)
    combined = (llm_score + stylo_score) / 2
    agree = gap <= AGREEMENT_GAP

    if not agree:
        attribution = "uncertain"
    elif combined >= AI_BAR:
        attribution = "likely_ai"
    elif combined <= HUMAN_BAR:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

    # Confidence shown to the reader is confidence in the attribution itself:
    # P(AI) for an AI verdict, P(human) for a human verdict, and how far from the
    # coin-flip midpoint for uncertain.
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
    }
