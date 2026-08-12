"""Safety checks on Aiwt-generated text before it reaches a real push
notification. Any failure here means the caller should fall back to the
static WATER_MESSAGE - a wrong or garbled AI message is worse than a
generic one.
"""

import re

MAX_LENGTH = 100
CLAUSE_SEPARATOR = "—"  # em dash

# Every word used across all 680 rows of wellness-ml's
# src/water_message/dataset_train.jsonl - a small closed vocabulary since
# it's a templated/combinatorial dataset. Verified zero false positives
# against 80 real local-model outputs. Any word outside this set is a
# hallucination by construction, not a legitimate paraphrase (confirmed:
# Render's cross-platform ONNX divergence produces off-topic nouns like
# "fiance"/"house"/"boss" that never appear anywhere in training data).
# wellness-backend has no runtime access to wellness-ml's dataset, so this
# is embedded directly - keep in sync if the training data ever changes.
TRAINING_VOCAB = {
    'a', 'afternoon', 'ahead', 'alive', 'all', 'almost', 'already', 'an',
    'and', 'any', 'around', 'as', 'at', 'away', 'barely', 'bed',
    'been', 'before', 'begins', 'behind', 'bit', "body's", 'building', 'busy',
    'but', 'by', 'call', 'catch', 'clean', 'climbing', 'close', 'coming',
    'consistent', 'counting', 'counts', 'day', 'dinner', 'doing', "don't", 'done',
    'down', 'early', 'evening', 'far', 'finish', 'fire', 'flowing', 'for',
    'fresh', 'from', 'get', 'gets', 'getting', 'glass', 'goal', 'going',
    'good', 'grab', 'great', 'had', 'half', 'halfway', 'heading', 'heats',
    'holding', 'hydrate', 'hydration', 'impressive', 'in', 'incredible', 'intake', 'into',
    'is', 'it', 'just', 'keep', 'keeps', 'kick', 'lag', 'lagging',
    'late', 'lately', 'later', 'let', "let's", 'line', 'little', 'logged',
    'looking', 'low', 'lunch', 'lunchtime', 'making', 'mark', 'midday', 'midpoint',
    'momentum', 'more', 'morning', 'moving', 'much', 'nearly', 'new', 'nice',
    'nicely', 'night', 'no', 'noon', 'not', 'now', 'nowhere', 'off',
    'on', 'one', 'only', 'or', 'over', 'pace', 'passed', 'past',
    'pressure', 'progress', 'push', 'quarter', 'quick', 'reliable', 'right', 'rise',
    'roll', 'rolls', 'rush', 'seriously', 'sets', 'sip', 'sipping', 'slate',
    'sleep', 'slip', 'slips', 'slow', 'slowly', 'small', 'sneak', 'so',
    'solid', 'some', 'start', 'started', 'stay', 'steady', 'still', 'stop',
    'streak', "streak's", 'stress', 'strong', 'than', 'that', 'the', 'there',
    "there's", 'this', 'ticking', 'time', 'to', 'today', "today's", 'tonight',
    'too', 'tracking', 'turn', 'two', 'unstoppable', 'up', 'waiting', 'water',
    "water's", 'way', 'well', 'win', 'winds', 'with', 'yet', 'you',
    "you're", "you've", 'young', 'your',
}


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

    # Closed-vocabulary check: a word absent from every training target is
    # a hallucination, not a paraphrase - this is what catches cases like
    # "your fiance"/"your house"/"your boss" that pass the shape check
    # above (correct em-dash, two clauses, ends in punctuation) but are
    # still nonsense, a failure mode the shape check alone can't see.
    words = re.findall(r"[a-z']+", message.lower().replace(CLAUSE_SEPARATOR, " "))
    if any(w not in TRAINING_VOCAB for w in words):
        return None

    # Degenerate repetition (same word 4+ times running) is a known failure
    # mode of small fine-tuned models producing garbage - this is exactly
    # the "reheatreheatreheat..." failure hit during development.
    words = message.lower().split()
    for i in range(len(words) - 3):
        if len(set(words[i : i + 4])) == 1:
            return None

    return message
