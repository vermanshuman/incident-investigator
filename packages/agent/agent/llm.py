"""Provider-agnostic structured LLM calls with token accounting.

LLM_PROVIDER = anthropic | openai | gemini | fake
LLM_MODEL       main reasoning model      (default claude-sonnet-5)
LLM_MODEL_SMALL cheap model for triage    (default claude-haiku-4-5)
LLM_RECORD      append every call to this cassette file
LLM_REPLAY      answer from this cassette instead of the API (zero cost)
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from agent import cassette

T = TypeVar("T", bound=BaseModel)

# $ per 1M tokens (input, output). Unknown models cost 0 in the ledger.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-5": (1.25, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
}

# Models with no price row report $0 and say so, rather than inventing a number.
# Gemini's free tier (AI Studio key) is the intended zero-cost path here.

DEFAULTS = {
    "anthropic": ("claude-sonnet-5", "claude-haiku-4-5"),
    "openai": ("gpt-4o", "gpt-4o-mini"),
    "gemini": ("gemini-3.8-flash", "gemini-3.8-flash"),
    "fake": ("fake", "fake"),
}


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "anthropic")


def model_name(small: bool) -> str:
    main, tiny = DEFAULTS[provider()]
    return os.getenv("LLM_MODEL_SMALL" if small else "LLM_MODEL") or (tiny if small else main)


# Claude 5-series and Opus 4.7+ reject sampling params (temperature/top_p/top_k).
_NO_SAMPLING = ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-5",
                "claude-fable-5", "claude-mythos-5")


def _chat_model(model: str) -> BaseChatModel:
    p = provider()
    if p == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs = {} if model.startswith(_NO_SAMPLING) else {"temperature": 0}
        return ChatAnthropic(model=model, max_tokens=4096, **kwargs)
    if p == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, temperature=0)
    if p == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model, temperature=0)
    raise ValueError(f"unknown LLM_PROVIDER {p!r}")


class Call(BaseModel):
    """Result of one structured call plus what it cost."""

    model_config = {"arbitrary_types_allowed": True}

    # Typed Any on purpose: declaring BaseModel makes Pydantic re-validate the
    # payload and lose the concrete schema when it is dumped.
    output: Any
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


# Tests and dry runs inject a scripted responder here: (schema, system, user) -> instance
FAKE_RESPONDER: Callable[[type[BaseModel], str, str], BaseModel] | None = None


def _json_loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _candidates(args: Any, fields: set[str]) -> Iterator[Any]:
    """Shapes a model may emit for a structured answer, most likely first.

    Models sometimes double-encode: the whole object as a JSON string inside a
    field, or the object wrapped in an extra layer. Unwrap those instead of
    paying for another call."""
    yield args
    args = _json_loads(args)
    yield args
    if not isinstance(args, dict):
        return
    # each value JSON-decoded (a list/dict sent as a string)
    yield {k: _json_loads(v) for k, v in args.items()}
    # the real object hidden inside one field
    for value in args.values():
        inner = _json_loads(value)
        if isinstance(inner, dict) and fields & inner.keys():
            yield inner
            yield {k: _json_loads(v) for k, v in inner.items()}


def _parse_raw(schema: type[T], raw: Any) -> T | None:
    """Best-effort recovery from a malformed structured response."""
    fields = set(schema.model_fields)
    sources = [tc.get("args") for tc in (getattr(raw, "tool_calls", None) or [])]
    content = getattr(raw, "content", None)
    if isinstance(content, str) and content.strip().startswith("{"):
        sources.append(content)
    for src in sources:
        for candidate in _candidates(src, fields):
            if isinstance(candidate, dict):
                try:
                    return schema.model_validate(candidate)
                except ValidationError:
                    continue
    return None


RETRY_NUDGE = ("\n\nYour previous reply was not valid. Answer by calling the tool ONCE with real "
               "JSON values - do not put JSON inside a string field.")


def _system_message(system: str) -> SystemMessage:
    """The system prompt is identical on every call, so cache it: cached input
    tokens cost ~10% of normal. Anthropic only; other providers cache
    automatically or not at all."""
    if provider() != "anthropic":
        return SystemMessage(content=system)
    return SystemMessage(content=[{"type": "text", "text": system,
                                   "cache_control": {"type": "ephemeral"}}])


def is_priced(model: str) -> bool:
    return model in PRICES


def _cost(model: str, inp: int, out: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return round((inp * pin + out * pout) / 1e6, 6)


def call_structured(schema: type[T], system: str, user: str, small: bool = False) -> Call:
    model = model_name(small)
    if provider() == "fake":
        if FAKE_RESPONDER is None:
            raise RuntimeError("LLM_PROVIDER=fake but no FAKE_RESPONDER installed")
        out = FAKE_RESPONDER(schema, system, user)
        return Call(output=out, model="fake", input_tokens=len(system + user) // 4,
                    output_tokens=len(out.model_dump_json()) // 4, cost_usd=0.0)

    # Replay: answer from the cassette, no API call, no cost.
    if cassette.replay_path() is not None:
        row = cassette.lookup(schema.__name__, model, system, user)
        usage = row.get("usage") or {}
        return Call(output=schema.model_validate(row["output"]), model=f"{row.get('model', model)} (replay)",
                    input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
                    cost_usd=0.0)

    llm = _chat_model(model).with_structured_output(schema, include_raw=True)
    inp = out = 0
    last_error: Any = None

    for attempt in range(2):
        prompt = user if attempt == 0 else user + RETRY_NUDGE
        result = llm.invoke([_system_message(system), HumanMessage(content=prompt)])
        raw = result["raw"]
        usage = getattr(raw, "usage_metadata", None) or {}
        inp += usage.get("input_tokens", 0)
        out += usage.get("output_tokens", 0)
        parsed = result["parsed"] or _parse_raw(schema, raw)
        if parsed is not None:
            cassette.save(schema.__name__, model, system, user, parsed.model_dump(mode="json"),
                          {"input_tokens": inp, "output_tokens": out})
            return Call(output=parsed, model=model, input_tokens=inp, output_tokens=out,
                        cost_usd=_cost(model, inp, out))
        last_error = result.get("parsing_error")

    raise RuntimeError(f"{schema.__name__}: model returned no usable structured output: {last_error}")
