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

logger = logging.getLogger(__name__)

MODEL_NAME = "Aiwt"
MODEL_VERSION = "v1"
ARTIFACT_FOLDER = "aiwt-v1"

ARTIFACT_DIR = Path(__file__).parent / "artifacts" / ARTIFACT_FOLDER
EOS_ID = 1
DECODER_START_ID = 0
MAX_NEW_TOKENS = 45

_state = {"loaded": False, "sp": None, "encoder": None, "decoder": None}
_cache: dict[str, str] = {}


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


def generate_water_message(input_text: str) -> str:
    """Raw call to Aiwt - no guardrails, no fallback. Callers must wrap this
    in guardrails.check(...) and a try/except, falling back to the static
    WATER_MESSAGE on any failure (see push_service.dispatch_water_due)."""
    if input_text in _cache:
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
        next_id = int(np.argmax(logits[0, -1]))
        if next_id == EOS_ID:
            break
        decoder_ids.append(next_id)

    message = sp.decode(decoder_ids[1:])  # drop the leading decoder-start token
    _cache[input_text] = message  # bounded: at most 80 distinct bucket combos
    return message
