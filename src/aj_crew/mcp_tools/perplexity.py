"""First-class Perplexity search and deep-research MCP tools for ``ajcrew-core``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aj_crew import mcp_core
from aj_crew.subscriptions.store import active_native_providers

PERPLEXITY_MCP_PATH = "/api/perplexity-mcp/query"


def schemas() -> list[dict[str, Any]]:
    """Tool descriptors for ``perplexity_search`` and ``perplexity_deep_research``."""
    return [
        {
            "name": "perplexity_search",
            "description": (
                "Run a live, source-cited web search through the connected Perplexity "
                "Sonar / Pro subscription. Returns an up-to-date synthesized answer "
                "with numbered URL citations."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The web search question or query.",
                    },
                    "recency": {
                        "type": "string",
                        "enum": ["hour", "day", "week", "month", "year"],
                        "description": "Optional recency filter for time-sensitive queries.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "perplexity_deep_research",
            "description": (
                "Run multi-step cited Pro research on a complex topic through the "
                "connected Perplexity subscription (`sonar-deep-research`). Returns "
                "a comprehensive report with numbered source citations."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The research question or topic to investigate.",
                    },
                    "focus": {
                        "type": "string",
                        "description": "Optional sub-questions or constraints to prioritize.",
                    },
                },
                "required": ["topic"],
                "additionalProperties": False,
            },
        },
    ]


def advertised() -> list[dict[str, Any]]:
    """Advertise Perplexity tools whenever Perplexity is configured and enabled."""
    try:
        if "perplexity" in active_native_providers():
            return schemas()
    except Exception:
        pass
    return []


def _run_perplexity_search(name: str, args: dict[str, Any]) -> str:
    del name
    query = str(args.get("query") or "").strip()
    if not query:
        return "Error: 'query' must be a non-empty string."
    recency = str(args.get("recency") or "").strip()
    payload: dict[str, Any] = {"mode": "search", "query": query}
    if recency:
        payload["recency"] = recency
    resp = mcp_core._post(PERPLEXITY_MCP_PATH, payload, timeout=60.0)
    if not isinstance(resp, dict) or not resp.get("ok"):
        err = resp.get("error") if isinstance(resp, dict) else "gateway unreachable"
        return f"Perplexity search failed: {err}"
    return str(resp.get("result") or "")


def _run_perplexity_deep_research(name: str, args: dict[str, Any]) -> str:
    del name
    topic = str(args.get("topic") or "").strip()
    if not topic:
        return "Error: 'topic' must be a non-empty string."
    focus = str(args.get("focus") or "").strip()
    query = f"{topic}\n\nFocus areas:\n{focus}" if focus else topic
    payload: dict[str, Any] = {"mode": "deep_research", "query": query}
    resp = mcp_core._post(PERPLEXITY_MCP_PATH, payload, timeout=180.0)
    if not isinstance(resp, dict) or not resp.get("ok"):
        err = resp.get("error") if isinstance(resp, dict) else "gateway unreachable"
        return f"Perplexity deep research failed: {err}"
    return str(resp.get("result") or "")


HANDLERS: dict[str, Callable[[str, dict[str, Any]], str]] = {
    "perplexity_search": _run_perplexity_search,
    "perplexity_deep_research": _run_perplexity_deep_research,
}
