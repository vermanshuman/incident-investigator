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
    cassette.reset()

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
    cassette.reset()
    assert llm.call_structured(Triage, SYSTEM, USER).output.severity == "high"


def test_drifted_prompt_still_replays_in_order(tmp_path, monkeypatch):
    """Prompts carry a timestamp and the evidence ledger, so they never match
    byte for byte; replay must still reproduce the recorded sequence."""
    path = tmp_path / "run.jsonl"
    monkeypatch.setenv("LLM_RECORD", str(path))
    cassette.save("Triage", "gemini-3.8-flash", SYSTEM, "recorded at 10:00", PAYLOAD, {})
    monkeypatch.delenv("LLM_RECORD")
    monkeypatch.setenv("LLM_REPLAY", str(path))
    cassette.reset()
    call = llm.call_structured(Triage, SYSTEM, "recorded at 11:47 - different prompt")
    assert call.output.severity == "high"


def test_exhausted_schema_is_explicit(tmp_path, monkeypatch):
    path = tmp_path / "one.jsonl"
    monkeypatch.setenv("LLM_RECORD", str(path))
    cassette.save("Triage", "m", SYSTEM, USER, PAYLOAD, {})
    monkeypatch.delenv("LLM_RECORD")
    monkeypatch.setenv("LLM_REPLAY", str(path))
    cassette.reset()
    llm.call_structured(Triage, SYSTEM, "first call consumes the only entry")
    with pytest.raises(cassette.MissingRecording, match="no unused Triage recording"):
        llm.call_structured(Triage, SYSTEM, "second call has nothing left")


def test_missing_cassette_file_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_REPLAY", str(tmp_path / "nope.jsonl"))
    cassette.reset()
    with pytest.raises(cassette.MissingRecording, match="cassette not found"):
        llm.call_structured(Triage, SYSTEM, USER)


def test_tool_results_replay_without_the_target_app(tmp_path, monkeypatch):
    """A replay must not depend on the live database: the recorded evidence is
    what makes an old run reproducible on a fresh clone."""
    from agent import tools

    path = tmp_path / "run.jsonl"
    monkeypatch.setenv("LLM_RECORD", str(path))
    monkeypatch.setitem(tools.TOOLS, "search_logs",
                        (lambda **kw: "raw", lambda raw: tools.ToolResult("- [log:7] boom", ["log:7"])))
    recorded, _, err = tools.run_tool("search_logs", {"level": "ERROR"})
    assert recorded.refs == ["log:7"] and err is None

    monkeypatch.delenv("LLM_RECORD")
    monkeypatch.setenv("LLM_REPLAY", str(path))
    cassette.reset()
    # the tool itself now raises: only a recorded result can answer
    monkeypatch.setitem(tools.TOOLS, "search_logs",
                        (lambda **kw: (_ for _ in ()).throw(AssertionError("tool must not run")), lambda raw: raw))
    replayed, _, err = tools.run_tool("search_logs", {"level": "ERROR"})
    assert replayed.summary == "- [log:7] boom"
    assert replayed.refs == ["log:7"]
    assert err is None


def test_tool_errors_are_recorded_and_replayed(tmp_path, monkeypatch):
    from agent import tools

    path = tmp_path / "run.jsonl"
    monkeypatch.setenv("LLM_RECORD", str(path))
    monkeypatch.setitem(tools.TOOLS, "get_metrics",
                        (lambda **kw: (_ for _ in ()).throw(ValueError("unknown metric cpu")), lambda raw: raw))
    _, _, err = tools.run_tool("get_metrics", {"metric": "cpu"})
    assert "unknown metric cpu" in err

    monkeypatch.delenv("LLM_RECORD")
    monkeypatch.setenv("LLM_REPLAY", str(path))
    cassette.reset()
    result, _, err = tools.run_tool("get_metrics", {"metric": "cpu"})
    assert "unknown metric cpu" in err and "tool error" in result.summary
