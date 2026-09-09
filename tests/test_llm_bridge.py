"""Tests for engine/llm_bridge.py streaming contract.

dispatch_ollama_turn_stream is the web port's live narrative path: yield clean
prose, withhold the [MECHANICAL PAYLOAD] tail from the UI, and accumulate
EVERYTHING into ctx["full_raw_text"] so the caller can still run
inspect_llm_output on the full text after streaming (CP-17).

The NDJSON transport (core.ollama.stream_generate) is monkeypatched to canned
frames — these tests are offline and never touch an Ollama engine.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

import engine.llm_bridge as lb
from engine.llm_bridge import LLMBridge

MODEL = "probe-model"


def _frames(*tokens):
    for t in tokens:
        yield {"response": t, "done": False}
    yield {"done": True}


def _run(monkeypatch, tokens, ctx=None):
    monkeypatch.setattr(lb, "stream_generate", lambda *a, **k: _frames(*tokens))
    c = {} if ctx is None else ctx
    chunks = list(LLMBridge().dispatch_ollama_turn_stream(MODEL, "SYS", "USER", c))
    return chunks, c


def test_plain_prose_streams_unchanged(monkeypatch):
    prose = "The goblin flees into the darkness, vanishing between the crates."
    chunks, ctx = _run(monkeypatch, [prose])
    assert "".join(chunks) == prose
    assert ctx["full_raw_text"] == prose


def test_split_marker_withheld_ctx_captures_all(monkeypatch):
    prose = "The goblin drops its rusty dagger. "
    payload = '{"requires_roll": false}'
    chunks, ctx = _run(monkeypatch, [prose, "[ME", "CHANICAL PAYLOAD] ", payload])
    assert "".join(chunks) == prose
    assert "[MECHANICAL" not in "".join(chunks)
    assert ctx["full_raw_text"] == prose + "[MECHANICAL PAYLOAD] " + payload


def test_single_frame_marker_with_trailing_payload(monkeypatch):
    prose = "You win! "
    tail = '[MECHANICAL PAYLOAD] {"hp_loss": 3}'
    chunks, ctx = _run(monkeypatch, [prose, tail])
    assert "".join(chunks) == prose
    assert ctx["full_raw_text"] == prose + tail


def test_empty_frames_skipped(monkeypatch):
    chunks, ctx = _run(monkeypatch, ["", "The fire crackles warmly.", "", " "])
    assert "".join(chunks) == "The fire crackles warmly. "
    assert ctx["full_raw_text"] == "The fire crackles warmly. "


def test_ctx_optional_defaults_to_fresh(monkeypatch):
    chunks, _ = _run(monkeypatch, ["Hello world. "])
    assert "".join(chunks) == "Hello world. "


def test_inspect_llm_output_on_ctx_full_text(monkeypatch):
    prose = "The goblin collapses. "
    tail = '[MECHANICAL PAYLOAD] {"requires_roll": false}'
    chunks, ctx = _run(monkeypatch, [prose, tail])
    stripped, mech = LLMBridge().inspect_llm_output(ctx["full_raw_text"])
    assert "".join(chunks).strip() == stripped
    assert stripped == "The goblin collapses."
    assert mech == {"requires_roll": False}