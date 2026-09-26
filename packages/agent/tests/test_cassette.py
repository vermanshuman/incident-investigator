"""Record and replay: a run reproduced with zero API calls."""

import pytest

from agent import cassette, llm
from agent.schemas import Triage

SYSTEM, USER = "sys prompt", "user prompt"
PAYLOAD = {"error_signature": "500s on /checkout", "affected_endpoints": ["/checkout"],
           "started_at": None, "severity": "high"}


def test_record_then_replay_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "run.jsonl"
    monkeypatch.setenv("LLM_RECORD", str(path))
    cassette.save("Triage", "claude-sonnet-5", SYSTEM, USER, PAYLOAD,
                  {"input_tokens": 1200, "output_tokens": 80})

    monkeypatch.delenv("LLM_RECORD")
    monkeypatch.setenv("LLM_REPLAY", str(path))
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5")
    cassette._cache.clear()

    call = llm.call_structured(Triage, SYSTEM, USER)
    assert call.output.error_signature == "500s on /checkout"
    assert call.cost_usd == 0.0  # replay is free
    assert call.input_tokens == 1200  # original usage preserved for reporting
    assert "replay" in call.model


def test_replay_falls_back_across_models(tmp_path, monkeypatch):
    path = tmp_path / "run.jsonl"
    monkeypatch.setenv("LLM_RECORD", str(path))
    cassette.save("Triage", "claude-opus-5", SYSTEM, USER, PAYLOAD, {})
    monkeypatch.delenv("LLM_RECORD")
    monkeypatch.setenv("LLM_REPLAY", str(path))
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5")  # recorded with a different model
    cassette._cache.clear()
    assert llm.call_structured(Triage, SYSTEM, USER).output.severity == "high"


def test_missing_recording_is_explicit(tmp_path, monkeypatch):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    monkeypatch.setenv("LLM_REPLAY", str(path))
    cassette._cache.clear()
    with pytest.raises(cassette.MissingRecording, match="not in cassette"):
        llm.call_structured(Triage, SYSTEM, "a prompt never recorded")
