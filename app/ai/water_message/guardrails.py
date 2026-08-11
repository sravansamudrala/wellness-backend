"""Safety checks on Aiwt-generated text before it reaches a real push
notification. Any failure here means the caller should fall back to the
static WATER_MESSAGE - a wrong or garbled AI message is worse than a
generic one.
"""

MAX_LENGTH = 100


def check(message: str) -> str | None:
    """Returns the message if it passes all checks, else None."""
    if not message or not message.strip():
        return None

    if len(message) > MAX_LENGTH:
        return None

    if not message.rstrip().endswith((".", "!", "?")):
        return None  # truncated mid-sentence

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
