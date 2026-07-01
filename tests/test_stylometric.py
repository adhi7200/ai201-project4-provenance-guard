"""Tests for the stylometric signal (pure Python, no network)."""

from signals import stylometric_signal

AI_TEXT = (
    "Artificial intelligence represents a transformative paradigm shift in modern "
    "society. It is important to note that while the benefits of AI are numerous, it "
    "is equally essential to consider the ethical implications. Furthermore, "
    "stakeholders across various sectors must collaborate to ensure responsible "
    "deployment. Moreover, ongoing research continues to shape the landscape."
)

HUMAN_TEXT = (
    "ok so i finally tried that new ramen place downtown and honestly? underwhelming. "
    "the broth was fine but they put WAY too much sodium in it and i was thirsty for "
    "like three hours after. my friend got the spicy version and said it was better. "
    "probably won't go back unless someone drags me there"
)


def test_ai_text_scores_higher_than_human_text():
    ai = stylometric_signal(AI_TEXT)["stylo_score"]
    human = stylometric_signal(HUMAN_TEXT)["stylo_score"]
    assert ai > human


def test_score_is_bounded():
    for text in (AI_TEXT, HUMAN_TEXT):
        s = stylometric_signal(text)["stylo_score"]
        assert 0.0 <= s <= 1.0


def test_short_text_abstains_to_neutral():
    r = stylometric_signal("Too short to judge.")
    assert r["stylo_score"] == 0.5


def test_transition_heavy_text_reads_as_ai():
    features = stylometric_signal(AI_TEXT)["features"]
    assert features["transition_density"] > 0.5
