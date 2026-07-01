"""Challenge prompts for the provenance certificate live writing challenge."""

import hashlib
import time

PROMPTS = [
    "Describe a moment when you changed your mind about something you felt strongly about.",
    "Write about a small everyday object that holds an unexpected memory for you.",
    "Describe a conversation that didn't go the way you expected.",
    "Write about a place that felt different the second time you visited it.",
    "Describe something you learned the hard way.",
    "Write about a time you misread a situation completely.",
    "Describe a habit you picked up without noticing when you started.",
    "Write about something you wish you had said at the time.",
]


def get_challenge():
    """Return a challenge dict with a prompt and a challenge_id derived from a timestamp."""
    idx = int(time.time()) % len(PROMPTS)
    prompt = PROMPTS[idx]
    challenge_id = hashlib.sha256(f"{prompt}{int(time.time() // 300)}".encode()).hexdigest()[:16]
    return {"challenge_id": challenge_id, "prompt": prompt}
