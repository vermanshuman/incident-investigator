"""Thin provider interface so the model can be swapped via LLM_PROVIDER."""

import os

from langchain_core.language_models import BaseChatModel


def get_llm(small: bool = False) -> BaseChatModel:
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    model = os.getenv("LLM_MODEL_SMALL" if small else "LLM_MODEL")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model or "claude-sonnet-5", temperature=0, max_tokens=4096)
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model or "gpt-4o", temperature=0)
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}")
