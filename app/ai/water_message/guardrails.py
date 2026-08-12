"""Safety checks on Aiwt-generated text before it reaches a real push
notification. Any failure here means the caller should fall back to the
static WATER_MESSAGE - a wrong or garbled AI message is worse than a
generic one.
"""

MAX_LENGTH = 100
CLAUSE_SEPARATOR = "—"  # em dash


def check(message: str) -> str | None:
    """Returns the message if it passes all checks, else None."""
    if not message or not message.strip():
        return None

    if len(message) > MAX_LENGTH:
        return None

    if not message.rstrip().endswith((".", "!", "?")):
        return None  # truncated mid-sentence

    # Verified against all 680 rows of wellness-ml's dataset_train.jsonl:
    # every real target is exactly two clauses joined by a single em dash
    # (e.g. "You're almost at your goal — don't stop now."). A decode
    # producing zero, two, or more separators is blending more than two
    # training-target clauses into one run-on - the exact shape the
    # garbled-notification bug took - not a valid generation.
    if message.count(CLAUSE_SEPARATOR) != 1:
        return None

    clause_a, clause_b = message.split(CLAUSE_SEPARATOR)
    if not clause_a.strip() or not clause_b.strip():
        return None

    # Training targets never contain digits (bucket phrasing is purely
    # qualitative, e.g. "quarter to halfway" rather than "43%") - any digit
    # in the output is a hallucination by definition, not a real number to
    # cross-check against context.
    if any(ch.isdigit() for ch in message):
        return None

    # Degenerate repetition (same word 4+ times running) is a known failure
    # mode of small fine-tuned models producing garbage - this is exactly
    # the "reheatreheatreheat..." failure hit during development.
    words = message.lower().split()
    for i in range(len(words) - 3):
        if len(set(words[i : i + 4])) == 1:
            return None

    return message
