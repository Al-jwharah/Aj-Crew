"""Capability-normalized streaming LLM adapters for ``aj_crew.acp.native_engine``.

Supports OpenAI-compatible & ChatGPT Codex SSE, Anthropic Messages SSE, Google
Gemini SSE, and Perplexity Sonar / Pro SSE with zero hardcoded model literals.
Automatically strips unsupported ``temperature`` / ``top_p`` fields on reasoning
models, maps ``effort`` levels, translates tool schemas, and retries once on a
400 schema error if an unlisted reasoning model rejects ``temperature``.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    kind: str  # "text" | "thinking" | "tool_call" | "usage"
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0


def _is_reasoning_model_id(raw_model: str) -> bool:
    lower = raw_model.lower()
    return (
        "reason" in lower
        or "thinking" in lower
        or lower.startswith(("o1", "o3", "o4"))
        or "deep-research" in lower
    )


def _openai_tools_payload(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


async def _iter_sse_json(resp: aiohttp.ClientResponse) -> AsyncIterator[dict[str, Any]]:
    buf = b""
    async for chunk in resp.content.iter_any():
        buf += chunk
        while b"\n" in buf:
            raw_line, buf = buf.split(b"\n", 1)
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                parsed = json.loads(data_str)
                if isinstance(parsed, dict):
                    yield parsed
            except json.JSONDecodeError:
                continue


async def stream_llm_turn(
    *,
    provider_cfg: dict[str, Any],
    raw_model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    effort: str,
) -> AsyncIterator[StreamChunk]:
    """Stream normalized chunks from the selected provider & model."""
    kind = str(provider_cfg.get("kind") or "openai_compat")
    if kind == "anthropic":
        async for ch in _stream_anthropic(
            provider_cfg=provider_cfg,
            raw_model=raw_model,
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            effort=effort,
        ):
            yield ch
        return
    if kind == "gemini":
        async for ch in _stream_gemini(
            provider_cfg=provider_cfg,
            raw_model=raw_model,
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            effort=effort,
        ):
            yield ch
        return
    async for ch in _stream_openai_or_perplexity(
        provider_cfg=provider_cfg,
        raw_model=raw_model,
        system_prompt=system_prompt,
        messages=messages,
        tools=tools,
        effort=effort,
    ):
        yield ch


async def _stream_openai_or_perplexity(
    *,
    provider_cfg: dict[str, Any],
    raw_model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    effort: str,
) -> AsyncIterator[StreamChunk]:
    kind = str(provider_cfg.get("kind") or "openai_compat")
    base_url = str(provider_cfg.get("base_url") or "").rstrip("/")
    creds = provider_cfg.get("credentials") or {}
    token = str(creds.get("access_token") or creds.get("api_key") or "").strip()

    headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    wire_msgs: list[dict[str, Any]] = []
    if system_prompt:
        wire_msgs.append({"role": "system", "content": system_prompt})
    wire_msgs.extend(messages)

    is_reasoning = _is_reasoning_model_id(raw_model)
    allow_tools = bool(tools) and not (
        kind == "perplexity"
        and ("deep-research" in raw_model.lower() or "reason" in raw_model.lower())
    )

    body: dict[str, Any] = {
        "model": raw_model,
        "messages": wire_msgs,
        "stream": True,
    }
    if not is_reasoning:
        body["temperature"] = 0.2
    if effort and effort not in ("auto", "off") and is_reasoning and kind != "perplexity":
        mapped_effort = {
            "minimal": "low",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "xhigh": "high",
            "max": "high",
        }.get(effort, "medium")
        body["reasoning_effort"] = mapped_effort
    if allow_tools:
        body["tools"] = _openai_tools_payload(tools)

    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        url = f"{base_url}/chat/completions"
        resp = await session.post(url, headers=headers, json=body)
        if resp.status == 400 and ("temperature" in body or "reasoning_effort" in body):
            await resp.release()
            body.pop("temperature", None)
            body.pop("reasoning_effort", None)
            resp = await session.post(url, headers=headers, json=body)
        async with resp:
            if resp.status >= 400:
                err_txt = await resp.text()
                raise RuntimeError(f"Provider HTTP {resp.status}: {err_txt[:400]}")

            tool_accum: dict[int, dict[str, str]] = {}
            citations: list[str] = []
            async for event in _iter_sse_json(resp):
                if isinstance(event.get("citations"), list):
                    citations = [str(u) for u in event["citations"]]
                usage = event.get("usage")
                if isinstance(usage, dict):
                    yield StreamChunk(
                        kind="usage",
                        input_tokens=int(usage.get("prompt_tokens") or 0),
                        output_tokens=int(usage.get("completion_tokens") or 0),
                    )
                for choice in event.get("choices") or []:
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict):
                        continue
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if isinstance(reasoning, str) and reasoning:
                        yield StreamChunk(kind="thinking", text=reasoning)
                    text = delta.get("content")
                    if isinstance(text, str) and text:
                        yield StreamChunk(kind="text", text=text)
                    for tc in delta.get("tool_calls") or []:
                        if not isinstance(tc, dict):
                            continue
                        idx = int(tc.get("index") or 0)
                        slot = tool_accum.setdefault(idx, {"id": "", "name": "", "args": ""})
                        if tc.get("id"):
                            slot["id"] = str(tc["id"])
                        fn = tc.get("function") or {}
                        if isinstance(fn, dict):
                            if fn.get("name"):
                                slot["name"] += str(fn["name"])
                            if fn.get("arguments"):
                                slot["args"] += str(fn["arguments"])

            if citations:
                cite_block = "\n\nSources:\n" + "\n".join(
                    f"[{i}] {u}" for i, u in enumerate(citations, 1)
                )
                yield StreamChunk(kind="text", text=cite_block)

            for idx in sorted(tool_accum):
                slot = tool_accum[idx]
                if not slot["name"]:
                    continue
                try:
                    parsed_args = json.loads(slot["args"]) if slot["args"] else {}
                except json.JSONDecodeError:
                    parsed_args = {}
                yield StreamChunk(
                    kind="tool_call",
                    tool_call_id=slot["id"] or f"call_{uuid.uuid4().hex[:10]}",
                    tool_name=slot["name"],
                    tool_args=parsed_args if isinstance(parsed_args, dict) else {},
                )


async def _stream_anthropic(
    *,
    provider_cfg: dict[str, Any],
    raw_model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    effort: str,
) -> AsyncIterator[StreamChunk]:
    base_url = str(provider_cfg.get("base_url") or "https://api.anthropic.com/v1").rstrip("/")
    creds = provider_cfg.get("credentials") or {}
    token = str(creds.get("api_key") or creds.get("access_token") or "").strip()
    headers = {
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    anth_msgs: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            anth_msgs.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id", ""),
                            "content": str(m.get("content") or ""),
                        }
                    ],
                }
            )
        elif role == "assistant" and m.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": str(m["content"])})
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                try:
                    inp = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    inp = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": inp,
                    }
                )
            anth_msgs.append({"role": "assistant", "content": blocks})
        else:
            anth_msgs.append(
                {
                    "role": "assistant" if role == "assistant" else "user",
                    "content": str(m.get("content") or ""),
                }
            )

    body: dict[str, Any] = {
        "model": raw_model,
        "max_tokens": 8192,
        "messages": anth_msgs,
        "stream": True,
    }
    if system_prompt:
        body["system"] = system_prompt
    if tools:
        body["tools"] = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
            }
            for t in tools
        ]
    if effort and effort not in ("auto", "off"):
        budget = {
            "minimal": 1024,
            "low": 2048,
            "medium": 4096,
            "high": 8192,
            "xhigh": 12000,
            "max": 16000,
        }.get(effort, 4096)
        body["thinking"] = {"type": "enabled", "budget_tokens": budget}
        body["max_tokens"] = budget + 8192

    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        resp = await session.post(f"{base_url}/messages", headers=headers, json=body)
        if resp.status == 400 and "thinking" in body:
            await resp.release()
            body.pop("thinking", None)
            body["max_tokens"] = 8192
            resp = await session.post(f"{base_url}/messages", headers=headers, json=body)
        async with resp:
            if resp.status >= 400:
                err_txt = await resp.text()
                raise RuntimeError(f"Anthropic HTTP {resp.status}: {err_txt[:400]}")

            active_tools: dict[int, dict[str, str]] = {}
            async for event in _iter_sse_json(resp):
                etype = event.get("type")
                if etype == "content_block_start":
                    idx = int(event.get("index") or 0)
                    cb = event.get("content_block") or {}
                    if cb.get("type") == "tool_use":
                        active_tools[idx] = {
                            "id": str(cb.get("id") or f"toolu_{uuid.uuid4().hex[:10]}"),
                            "name": str(cb.get("name") or ""),
                            "json": "",
                        }
                elif etype == "content_block_delta":
                    idx = int(event.get("index") or 0)
                    delta = event.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta" and delta.get("text"):
                        yield StreamChunk(kind="text", text=str(delta["text"]))
                    elif dtype == "thinking_delta" and delta.get("thinking"):
                        yield StreamChunk(kind="thinking", text=str(delta["thinking"]))
                    elif dtype == "input_json_delta" and idx in active_tools:
                        active_tools[idx]["json"] += str(delta.get("partial_json") or "")
                elif etype == "message_delta":
                    usage = event.get("usage") or {}
                    if isinstance(usage, dict) and usage.get("output_tokens"):
                        yield StreamChunk(kind="usage", output_tokens=int(usage["output_tokens"]))
            for idx in sorted(active_tools):
                slot = active_tools[idx]
                try:
                    parsed = json.loads(slot["json"]) if slot["json"] else {}
                except json.JSONDecodeError:
                    parsed = {}
                yield StreamChunk(
                    kind="tool_call",
                    tool_call_id=slot["id"],
                    tool_name=slot["name"],
                    tool_args=parsed if isinstance(parsed, dict) else {},
                )


async def _stream_gemini(
    *,
    provider_cfg: dict[str, Any],
    raw_model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    effort: str,
) -> AsyncIterator[StreamChunk]:
    base_url = str(
        provider_cfg.get("base_url") or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    creds = provider_cfg.get("credentials") or {}
    headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    params: dict[str, str] = {"alt": "sse"}
    if creds.get("access_token"):
        headers["Authorization"] = f"Bearer {creds['access_token']}"
    elif creds.get("api_key"):
        params["key"] = str(creds["api_key"])

    contents: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": str(m.get("name") or "tool"),
                                "response": {"result": str(m.get("content") or "")},
                            }
                        }
                    ],
                }
            )
        elif role == "assistant" and m.get("tool_calls"):
            parts: list[dict[str, Any]] = []
            if m.get("content"):
                parts.append({"text": str(m["content"])})
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                try:
                    args_obj = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args_obj = {}
                parts.append({"functionCall": {"name": fn.get("name", ""), "args": args_obj}})
            contents.append({"role": "model", "parts": parts})
        else:
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": str(m.get("content") or "")}],
                }
            )

    body: dict[str, Any] = {"contents": contents}
    if system_prompt:
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    if tools:
        decls = []
        for t in tools:
            schema = dict(t.get("inputSchema") or {"type": "object", "properties": {}})
            schema.pop("additionalProperties", None)
            schema.pop("$schema", None)
            decls.append(
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": schema,
                }
            )
        body["tools"] = [{"functionDeclarations": decls}]

    timeout = aiohttp.ClientTimeout(total=300)
    url = f"{base_url}/models/{raw_model}:streamGenerateContent"
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, params=params, json=body) as resp:
            if resp.status >= 400:
                err_txt = await resp.text()
                raise RuntimeError(f"Gemini HTTP {resp.status}: {err_txt[:400]}")
            async for event in _iter_sse_json(resp):
                usage = event.get("usageMetadata")
                if isinstance(usage, dict):
                    yield StreamChunk(
                        kind="usage",
                        input_tokens=int(usage.get("promptTokenCount") or 0),
                        output_tokens=int(usage.get("candidatesTokenCount") or 0),
                    )
                for cand in event.get("candidates") or []:
                    content = (cand or {}).get("content") or {}
                    for part in content.get("parts") or []:
                        if not isinstance(part, dict):
                            continue
                        if part.get("thought") is True and part.get("text"):
                            yield StreamChunk(kind="thinking", text=str(part["text"]))
                        elif "text" in part and part["text"]:
                            yield StreamChunk(kind="text", text=str(part["text"]))
                        elif "functionCall" in part and isinstance(part["functionCall"], dict):
                            fc = part["functionCall"]
                            yield StreamChunk(
                                kind="tool_call",
                                tool_call_id=f"call_{uuid.uuid4().hex[:10]}",
                                tool_name=str(fc.get("name") or ""),
                                tool_args=dict(fc.get("args") or {}),
                            )
