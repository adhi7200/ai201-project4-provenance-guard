"""Transparency label generation.

Maps an attribution + confidence into the reader-facing label text. The three
variants are the verbatim wording from planning.md: neutral and non-accusatory,
with the confidence shown as a percentage so a non-technical reader can weigh it.
"""

_TEMPLATES = {
    "likely_human": (
        "This text reads as human-written (confidence: {pct}%). "
        "No strong AI-generation signals were detected."
    ),
    "likely_ai": (
        "This text shows signals commonly associated with AI generation "
        "(confidence: {pct}%). This is an automated estimate, not a verdict. "
        "If you wrote it yourself, you can appeal."
    ),
    "uncertain": (
        "Attribution uncertain (confidence: {pct}%). Our signals were mixed or "
        "inconclusive for this text, so treat its origin as unconfirmed."
    ),
}


def make_label(attribution, display_confidence):
    """Return the label text for an attribution and its display confidence (0..1)."""
    pct = round(display_confidence * 100)
    template = _TEMPLATES.get(attribution, _TEMPLATES["uncertain"])
    return template.format(pct=pct)
