"""Loads Aiwt (our fine-tuned flan-t5-small water-message model, quantized
ONNX, ~93MB) and generates a push-notification body from a bucketed context
string.

Deliberately avoids optimum/transformers/torch - those pull in ~450MB of
import-time RAM (measured), which alone would exceed Render free tier's
512MB ceiling. onnxruntime + sentencepiece together measure ~45MB. See
[[project-ai-ml-roadmap]] / the water-message plan for the full analysis.

The encoder/decoder sessions are lazy-loaded singletons - Aiwt's ~93MB of
weights only load into memory on first use, not at import time (matters if
this feature is ever disabled via settings.water_message_model_enabled).
"""

import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort
import sentencepiece as spm

from app.ai.water_message import guardrails

logger = logging.getLogger(__name__)

MODEL_NAME = "Aiwt"
MODEL_VERSION = "v1"
ARTIFACT_FOLDER = "aiwt-v1"

ARTIFACT_DIR = Path(__file__).parent / "artifacts" / ARTIFACT_FOLDER
EOS_ID = 1
DECODER_START_ID = 0
MAX_NEW_TOKENS = 45

# Quantized ONNX inference isn't bit-identical across CPU architectures
# (confirmed: Render vs local dev diverge on identical model files/runtime
# version - see project_water_message_model memory). Greedy decoding is
# deterministic, so a bucket that decodes badly on a given machine fails
# the same way forever. Sampling gives retries genuine randomness, so
# they can land on a different, hopefully-valid path instead of repeating
# the same bad output.
MAX_VALIDATION_ATTEMPTS = 3
SAMPLE_TEMPERATURE = 0.9

_state = {"loaded": False, "sp": None, "encoder": None, "decoder": None}
_cache: dict[str, str] = {}  # raw greedy-decode cache - may hold bad output
_good_cache: dict[str, str] = {}  # only ever holds guardrail-passing output


def is_available() -> bool:
    return (ARTIFACT_DIR / "encoder_model.onnx").exists()


def _load() -> None:
    if _state["loaded"]:
        return
    _state["sp"] = spm.SentencePieceProcessor(model_file=str(ARTIFACT_DIR / "spiece.model"))
    _state["encoder"] = ort.InferenceSession(str(ARTIFACT_DIR / "encoder_model.onnx"))
    _state["decoder"] = ort.InferenceSession(str(ARTIFACT_DIR / "decoder_model.onnx"))
    _state["loaded"] = True
    logger.info("%s %s loaded from %s", MODEL_NAME, MODEL_VERSION, ARTIFACT_DIR)


def _pick_next_token(logits_row: np.ndarray, sample: bool, temperature: float) -> int:
    if not sample:
        return int(np.argmax(logits_row))
    scaled = logits_row / temperature
    scaled = scaled - scaled.max()  # numerical stability before exp
    probs = np.exp(scaled)
    probs /= probs.sum()
    return int(np.random.choice(len(probs), p=probs))


def generate_water_message(input_text: str, sample: bool = False, temperature: float = 1.0) -> str:
    """Raw call to Aiwt - no guardrails, no fallback. Callers must wrap this
    in guardrails.check(...) and a try/except, falling back to the static
    WATER_MESSAGE on any failure (see push_service.dispatch_water_due).
    Prefer generate_validated_water_message for production use - it
    retries with sampling on a guardrail failure instead of accepting a
    single deterministic (and possibly bad) greedy decode.

    sample=False (default) reuses the deterministic-output cache; sampled
    calls always run fresh since caching a random draw as "the" output
    for an input would defeat the point of sampling."""
    if not sample and input_text in _cache:
        return _cache[input_text]

    _load()
    sp, encoder, decoder = _state["sp"], _state["encoder"], _state["decoder"]

    input_ids = np.array([sp.encode(input_text) + [EOS_ID]], dtype=np.int64)
    attention_mask = np.ones_like(input_ids)

    encoder_hidden_states = encoder.run(
        None, {"input_ids": input_ids, "attention_mask": attention_mask}
    )[0]

    decoder_ids = [DECODER_START_ID]
    for _ in range(MAX_NEW_TOKENS):
        decoder_input = np.array([decoder_ids], dtype=np.int64)
        logits = decoder.run(
            None,
            {
                "encoder_attention_mask": attention_mask,
                "input_ids": decoder_input,
                "encoder_hidden_states": encoder_hidden_states,
            },
        )[0]
        next_id = _pick_next_token(logits[0, -1], sample, temperature)
        if next_id == EOS_ID:
            break
        decoder_ids.append(next_id)

    message = sp.decode(decoder_ids[1:])  # drop the leading decoder-start token
    if not sample:
        _cache[input_text] = message  # bounded: at most 80 distinct bucket combos
    return message


def generate_validated_water_message(input_text: str) -> str | None:
    """Tries greedy decode first, then up to MAX_VALIDATION_ATTEMPTS-1
    sampled retries, checking guardrails.check() after each attempt.
    Returns the first guardrail-passing message (and caches it - this
    cache only ever holds validated-good output, so a bucket that fails
    every attempt today gets a fresh, differently-sampled chance on the
    next call instead of being stuck). Returns None if every attempt
    fails - caller should fall back to the static WATER_MESSAGE."""
    if input_text in _good_cache:
        return _good_cache[input_text]

    for attempt in range(MAX_VALIDATION_ATTEMPTS):
        sample = attempt > 0  # first attempt greedy, then sampled retries
        raw = generate_water_message(input_text, sample=sample, temperature=SAMPLE_TEMPERATURE)
        checked = guardrails.check(raw)
        if checked is not None:
            _good_cache[input_text] = checked
            return checked

    return None
