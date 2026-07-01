"""Tests for the weighted-ensemble confidence scoring (pure logic, no network)."""

from scoring import score


def test_agreeing_high_scores_yield_likely_ai():
    r = score({"llm": 0.85, "stylo": 0.75, "compression": 0.8})
    assert r["agree"] is True
    assert r["attribution"] == "likely_ai"
    assert r["display_confidence"] == r["combined"]


def test_agreeing_low_scores_yield_likely_human():
    r = score({"llm": 0.15, "stylo": 0.25, "compression": 0.2})
    assert r["agree"] is True
    assert r["attribution"] == "likely_human"
    assert r["display_confidence"] == round(1 - r["combined"], 3)


def test_wide_spread_forces_uncertain():
    # llm says AI, stylo says human: spread > gate must override the mean.
    r = score({"llm": 0.90, "stylo": 0.20, "compression": 0.5})
    assert r["agree"] is False
    assert r["attribution"] == "uncertain"


def test_midband_is_uncertain():
    r = score({"llm": 0.55, "stylo": 0.55, "compression": 0.55})
    assert r["attribution"] == "uncertain"


def test_asymmetric_bars_favor_the_creator():
    # 0.60 P(AI) is below the 0.70 AI bar -> not labeled AI.
    assert score({"llm": 0.60, "stylo": 0.60})["attribution"] == "uncertain"
    # 0.35 P(AI) clears the more lenient human bar -> labeled human.
    assert score({"llm": 0.35, "stylo": 0.35})["attribution"] == "likely_human"


def test_uncertain_confidence_is_not_misleadingly_high():
    r = score({"llm": 0.48, "stylo": 0.52})
    assert r["attribution"] == "uncertain"
    assert r["display_confidence"] <= 0.6


def test_weighting_favors_the_llm_signal():
    # Same three values, but llm is heaviest, so the combined leans toward llm.
    r = score({"llm": 0.9, "stylo": 0.3, "compression": 0.3})
    # Weighted mean = .5*.9 + .3*.3 + .2*.3 = 0.60; a plain mean would be 0.50.
    assert r["combined"] == 0.6


def test_single_signal_still_scores():
    r = score({"llm": 0.9})
    assert r["combined"] == 0.9
    assert r["attribution"] == "likely_ai"
