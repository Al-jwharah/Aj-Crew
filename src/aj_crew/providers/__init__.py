"""LLM provider abstraction — decouple from kiro-cli ACP."""

from __future__ import annotations

from aj_crew.providers.base import LLMEvent, LLMProvider

__all__ = ["LLMEvent", "LLMProvider"]
