"""Tests for the compression / predictability signal (pure Python, no network)."""

from signals import compression_signal

# Highly repetitive, low-entropy text compresses small -> AI-like.
REPETITIVE = (
    "The system is efficient. The system is reliable. The system is scalable. "
    "The system is efficient. The system is reliable. The system is scalable. "
    "The system is efficient. The system is reliable. The system is scalable. "
    "The system is efficient. The system is reliable. The system is scalable."
)

# Varied, higher-entropy text compresses less -> human-like.
VARIED = (
    "Rain hammered the tin roof while my grandmother argued with the radio about "
    "quantum physics. Somewhere a dog invented a new bark. I burned the toast, "
    "again, and blamed the toaster's obvious grudge against Tuesdays and jazz."
)


def test_redundant_text_fires_as_ai():
    r = compression_signal(REPETITIVE)
    assert r["informative"] is True
    assert r["compression_score"] > 0.5
    assert 0.0 <= r["compression_score"] <= 1.0


def test_ordinary_prose_abstains():
    # Varied, ordinary-entropy prose carries no redundancy signal, so it abstains.
    r = compression_signal(VARIED)
    assert r["informative"] is False
    assert r["compression_score"] is None


def test_short_text_abstains():
    r = compression_signal("Too short to compress meaningfully.")
    assert r["informative"] is False
    assert r["compression_score"] is None
    assert r["ratio"] is None
