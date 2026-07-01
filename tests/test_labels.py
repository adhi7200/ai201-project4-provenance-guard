"""Tests for transparency label generation."""

from labels import make_label


def test_all_three_variants_are_distinct():
    ai = make_label("likely_ai", 0.78)
    human = make_label("likely_human", 0.90)
    uncertain = make_label("uncertain", 0.55)
    assert ai != human != uncertain
    assert len({ai, human, uncertain}) == 3


def test_confidence_is_rendered_as_percentage():
    assert "78%" in make_label("likely_ai", 0.78)
    assert "90%" in make_label("likely_human", 0.90)


def test_ai_label_mentions_appeal():
    assert "appeal" in make_label("likely_ai", 0.72).lower()


def test_unknown_attribution_falls_back_to_uncertain():
    assert make_label("something_else", 0.5) == make_label("uncertain", 0.5)
