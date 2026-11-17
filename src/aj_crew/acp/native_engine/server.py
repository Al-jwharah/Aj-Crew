"""Multiplexed stdio ACP JSON-RPC 2.0 server for ``aj_crew.acp.native_engine``."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aj_crew.acp.harness.strands_keys import discard_keys_file
from aj_crew.acp.native_engine import NATIVE_ENGINE_VERSION
from aj_crew.acp.native_engine.builtin_tools import BUILTIN_TOOL_SCHEMAS, execute_builtin_tool
from aj_crew.acp.native_engine.llm_adapters import stream_llm_turn
from aj_crew.acp.native_engine.mcp_bridge import SessionMcpBridge
from aj_crew.config.paths import data_home

logger = logging.getLogger(__name__)

KEYS_FILE_ENV = "AJCREW_NATIVE_KEYS_FILE"
MAX_TOOL_ROUNDS = 24


@dataclass
class NativeSessionState:
    session_id: str
    cwd: str
    active_mode: str = "default"
    custom_agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    selected_model: str = "auto"
    selected_effort: str = "auto"
    messages: list[dict[str, Any]] = field(default_factory=list)
    mcp_bridge: SessionMcpBridge = field(default_factory=SessionMcpBridge)
    mcp_tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    builtin_tools_allowed: list[dict[str, Any]] = field(default_factory=list)
    zero_tools: bool = False
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    steer_queue: list[str] = field(default_factory=list)


class NativeAcpServer:
    """In-tree multiplexed ACP v1 server speaking stdio JSON-RPC to ``AcpRuntime``."""

    def __init__(self, provider_bundle: dict[str, dict[str, Any]]) -> None:
        self._providers = provider_bundle
        self._sessions: dict[str, NativeSessionState] = {}
        self._next_rpc_id = 1000
        self._pending_client_reqs: dict[int | str, asyncio.Future[dict[str, Any]]] = {}
        self._write_lock = asyncio.Lock()

    def _sessions_dir(self) -> Path:
        d = data_home() / "sessions" / "native"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _persist_session(self, sess: NativeSessionState) -> None:
        try:
            target = self._sessions_dir() / f"{sess.session_id}.json"
            payload = {
                "session_id": sess.session_id,
                "cwd": sess.cwd,
                "active_mode": sess.active_mode,
                "selected_model": sess.selected_model,
                "selected_effort": sess.selected_effort,
                "messages": sess.messages[-120:],
            }
            target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.debug("Could not persist native session %s", sess.session_id, exc_info=True)

    def _load_persisted_messages(self, session_id: str) -> list[dict[str, Any]] | None:
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        if not safe_id:
            return None
        target = self._sessions_dir() / f"{safe_id}.json"
        if not target.is_file():
            return None
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            msgs = raw.get("messages") if isinstance(raw, dict) else None
            return [m for m in msgs if isinstance(m, dict)] if isinstance(msgs, list) else []
        except Exception:
            return None

    async def _send_frame(self, frame: dict[str, Any]) -> None:
        line = json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n"
        async with self._write_lock:
            sys.stdout.write(line)
            sys.stdout.flush()

    async def _notify_update(self, session_id: str, update: dict[str, Any]) -> None:
        await self._send_frame(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": session_id, "update": update},
            }
        )

    async def _request_client(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        req_id = self._next_rpc_id
        self._next_rpc_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_client_reqs[req_id] = fut
        await self._send_frame({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        resp = await fut
        if "error" in resp:
            raise RuntimeError(str(resp["error"]))
        res = resp.get("result")
        return res if isinstance(res, dict) else {}

    def _reload_live_providers_if_empty(self) -> None:
        if self._providers:
            return
        try:
            from aj_crew.subscriptions.store import resolve_all_native_provider_credentials

            self._providers = resolve_all_native_provider_credentials()
        except Exception:
            pass

    def _advertised_model_options(self, current: str) -> list[dict[str, str]]:
        self._reload_live_providers_if_empty()
        opts = [{"value": "auto", "name": "Auto (Active Provider Default)"}]
        for pid, pcfg in self._providers.items():
            dmodel = str(pcfg.get("default_model") or "").strip()
            if dmodel:
                val = dmodel if "/" in dmodel else f"{pid}/{dmodel}"
                opts.append({"value": val, "name": f"{pcfg.get('label', pid)}: {dmodel}"})
        if current and all(o["value"] != current for o in opts):
            opts.append({"value": current, "name": current})
        return opts

    def _config_options(self, sess: NativeSessionState) -> list[dict[str, Any]]:
        return [
            {
                "id": "model",
                "name": "Model",
                "category": "model",
                "type": "select",
                "currentValue": sess.selected_model or "auto",
                "options": self._advertised_model_options(sess.selected_model or "auto"),
            },
            {
                "id": "effort",
                "name": "Reasoning Effort",
                "category": "thought_level",
                "type": "select",
                "currentValue": sess.selected_effort or "auto",
                "options": [
                    {"value": lvl, "name": lvl.title()}
                    for lvl in ("auto", "off", "minimal", "low", "medium", "high", "xhigh", "max")
                ],
            },
        ]

    def _modes_block(self, sess: NativeSessionState) -> dict[str, Any]:
        modes = [{"id": "default", "name": "Default", "_meta": {"kiro": {"origin": "client"}}}]
        for aid, spec in sess.custom_agents.items():
            modes.append(
                {
                    "id": aid,
                    "name": str(spec.get("name") or aid),
                    "description": str(spec.get("description") or ""),
                    "_meta": {"kiro": {"origin": "client"}},
                }
            )
        return {"currentModeId": sess.active_mode, "availableModes": modes}

    def _apply_agent_tool_filter(self, sess: NativeSessionState) -> None:
        spec = sess.custom_agents.get(sess.active_mode) or {}
        tools_field = spec.get("tools")
        excluded = {str(x) for x in (spec.get("excludedTools") or [])}
        if isinstance(tools_field, list) and len(tools_field) == 0:
            sess.zero_tools = True
            sess.builtin_tools_allowed = []
            return
        sess.zero_tools = False
        allow_all = tools_field is None or "*" in (tools_field or [])
        allowed_set = {str(x) for x in (tools_field or [])}
        kept: list[dict[str, Any]] = []
        for bt in BUILTIN_TOOL_SCHEMAS:
            bname = bt["name"]
            aliases = {bname}
            if bname == "fs_read":
                aliases |= {"read", "read_file"}
            elif bname == "fs_write":
                aliases |= {"write", "write_file"}
            elif bname == "execute_bash":
                aliases |= {"shell", "bash", "run_command"}
            if aliases & excluded:
                continue
            if allow_all or (aliases & allowed_set):
                kept.append(bt)
        sess.builtin_tools_allowed = kept

    async def _setup_session(
        self,
        session_id: str,
        params: dict[str, Any],
        *,
        restored_msgs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        cwd = str(params.get("cwd") or os.getcwd())
        meta = params.get("_meta") or {}
        kiro_meta = meta.get("kiro") if isinstance(meta, dict) else {}
        raw_agents = (kiro_meta.get("customAgents") if isinstance(kiro_meta, dict) else None) or []

        custom_map: dict[str, dict[str, Any]] = {}
        merged_servers: dict[str, dict[str, Any]] = {}
        excluded_tags: set[str] = set()
        for entry in raw_agents:
            if not isinstance(entry, dict):
                continue
            aid = str(entry.get("id") or entry.get("name") or "").strip()
            if aid:
                custom_map[aid] = entry
            for ex in entry.get("excludedTools") or []:
                excluded_tags.add(str(ex))
            s_block = entry.get("mcpServers")
            if isinstance(s_block, dict):
                for sname, scfg in s_block.items():
                    if isinstance(scfg, dict):
                        merged_servers[str(sname)] = dict(scfg)

        for elem in params.get("mcpServers") or []:
            if isinstance(elem, dict) and elem.get("name"):
                merged_servers[str(elem["name"])] = dict(elem)

        active_mode = next(iter(custom_map), "default")
        sess = NativeSessionState(
            session_id=session_id,
            cwd=cwd,
            active_mode=active_mode,
            custom_agents=custom_map,
            messages=list(restored_msgs or []),
        )
        self._apply_agent_tool_filter(sess)
        if not sess.zero_tools and merged_servers:
            connected_tools = await sess.mcp_bridge.connect_all(
                merged_servers, cwd=cwd, excluded_tags=excluded_tags
            )
            sess.mcp_tools = {t["qualified_name"]: t for t in connected_tools}

        self._sessions[session_id] = sess

        # Emit MCP status notification expected by AcpRuntime's KAS/Native readiness tracker
        await self._send_frame(
            {
                "jsonrpc": "2.0",
                "method": "_kiro/mcp/status",
                "params": {
                    "sessionId": session_id,
                    "servers": [
                        {"name": k, "status": v}
                        for k, v in sess.mcp_bridge.status_by_server.items()
                    ],
                },
            }
        )
        return {
            "sessionId": session_id,
            "modes": self._modes_block(sess),
            "configOptions": self._config_options(sess),
        }

    def _resolve_provider_and_model(self, sess: NativeSessionState) -> tuple[dict[str, Any], str]:
        self._reload_live_providers_if_empty()
        if not self._providers:
            raise RuntimeError(
                "Aj Crew Native has no connected subscription or model provider key. "
                "Connect ChatGPT, Google Gemini, Perplexity, Local Ollama, or an API key "
                "from Settings -> Agent Harness -> Subscriptions & Providers."
            )
        pick = (sess.selected_model or "auto").strip()
        if pick and pick != "auto" and "/" in pick:
            pid, raw_model = pick.split("/", 1)
            if pid in self._providers:
                return self._providers[pid], raw_model
        first_pid, first_cfg = next(iter(self._providers.items()))
        if pick and pick != "auto":
            return first_cfg, pick
        configured_default = str(first_cfg.get("default_model") or "").strip()
        if configured_default:
            return first_cfg, configured_default.removeprefix(f"{first_pid}/")
        # Discover first live model from provider if no default_model was pinned
        raise ValueError(f"__discover_first__:{first_pid}")

    async def _ask_permission(
        self,
        sess: NativeSessionState,
        *,
        tc_id: str,
        title: str,
        kind: str,
        raw_input: dict[str, Any],
        kiro_meta: dict[str, Any],
    ) -> bool:
        params = {
            "sessionId": sess.session_id,
            "toolCall": {
                "toolCallId": tc_id,
                "title": title,
                "kind": kind,
                "status": "pending",
                "rawInput": raw_input,
                "_meta": {"kiro": kiro_meta},
            },
            "options": [
                {"optionId": "allow_once", "name": "Allow", "kind": "allow_once"},
                {"optionId": "reject_once", "name": "Deny", "kind": "reject_once"},
            ],
        }
        res = await self._request_client("session/request_permission", params)
        outcome = res.get("outcome") or {}
        if isinstance(outcome, dict):
            chosen = str(outcome.get("optionId") or "")
            return chosen.startswith("allow")
        return str(res.get("optionId") or "").startswith("allow")

    async def _handle_prompt(self, req_id: Any, params: dict[str, Any]) -> None:
        session_id = str(params.get("sessionId") or "")
        sess = self._sessions.get(session_id)
        if sess is None:
            await self._send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Session not found"},
                }
            )
            return

        sess.cancel_event.clear()
        blocks = params.get("prompt") or []
        text_parts = [
            str(b.get("text") or "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        user_text = "\n".join(p for p in text_parts if p).strip()

        if user_text == "/compact":
            kept = sess.messages[-6:]
            sess.messages = [
                {"role": "user", "content": "[Compacted earlier conversation context]"},
                *kept,
            ]
            self._persist_session(sess)
            await self._notify_update(
                session_id,
                {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "Compaction complete."},
                },
            )
            await self._send_frame(
                {"jsonrpc": "2.0", "id": req_id, "result": {"stopReason": "end_turn"}}
            )
            return

        sess.messages.append({"role": "user", "content": user_text})
        spec = sess.custom_agents.get(sess.active_mode) or {}
        sys_prompt = str(spec.get("prompt") or "")

        try:
            try:
                provider_cfg, raw_model = self._resolve_provider_and_model(sess)
            except ValueError as disc:
                pid = str(disc).split(":", 1)[1]
                from aj_crew.subscriptions.discovery import discover_provider_models

                found = await discover_provider_models(pid)
                if not found:
                    raise RuntimeError(
                        f"Provider {pid!r} returned no models. Set a model in Settings -> Agent Harness."
                    ) from None
                provider_cfg = self._providers[pid]
                raw_model = found[0].raw_model

            all_tools: list[dict[str, Any]] = []
            if not sess.zero_tools:
                all_tools.extend(sess.builtin_tools_allowed)
                for qname, mtool in sess.mcp_tools.items():
                    all_tools.append(
                        {
                            "name": qname,
                            "description": mtool["description"],
                            "inputSchema": mtool["inputSchema"],
                        }
                    )

            total_in = 0
            total_out = 0
            for _round in range(MAX_TOOL_ROUNDS):
                if sess.cancel_event.is_set():
                    await self._send_frame(
                        {"jsonrpc": "2.0", "id": req_id, "result": {"stopReason": "cancelled"}}
                    )
                    return

                if sess.steer_queue:
                    steered = "\n".join(sess.steer_queue)
                    sess.steer_queue.clear()
                    sess.messages.append({"role": "user", "content": steered})

                assistant_text = ""
                pending_calls: list[tuple[str, str, dict[str, Any]]] = []
                async for chunk in stream_llm_turn(
                    provider_cfg=provider_cfg,
                    raw_model=raw_model,
                    system_prompt=sys_prompt,
                    messages=sess.messages,
                    tools=all_tools,
                    effort=sess.selected_effort,
                ):
                    if sess.cancel_event.is_set():
                        break
                    if chunk.kind == "thinking" and chunk.text:
                        await self._notify_update(
                            session_id,
                            {
                                "sessionUpdate": "agent_thought_chunk",
                                "content": {"type": "text", "text": chunk.text},
                            },
                        )
                    elif chunk.kind == "text" and chunk.text:
                        assistant_text += chunk.text
                        await self._notify_update(
                            session_id,
                            {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": chunk.text},
                            },
                        )
                    elif chunk.kind == "tool_call":
                        pending_calls.append((chunk.tool_call_id, chunk.tool_name, chunk.tool_args))
                    elif chunk.kind == "usage":
                        total_in += chunk.input_tokens
                        total_out += chunk.output_tokens

                if sess.cancel_event.is_set():
                    await self._send_frame(
                        {"jsonrpc": "2.0", "id": req_id, "result": {"stopReason": "cancelled"}}
                    )
                    return

                if not pending_calls:
                    sess.messages.append({"role": "assistant", "content": assistant_text})
                    self._persist_session(sess)
                    await self._send_frame(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "stopReason": "end_turn",
                                "usage": {"inputTokens": total_in, "outputTokens": total_out},
                            },
                        }
                    )
                    return

                sess.messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_text,
                        "tool_calls": [
                            {
                                "id": tid,
                                "type": "function",
                                "function": {"name": tname, "arguments": json.dumps(targs)},
                            }
                            for tid, tname, targs in pending_calls
                        ],
                    }
                )

                for tid, tname, targs in pending_calls:
                    is_mcp = tname in sess.mcp_tools
                    if is_mcp:
                        mt = sess.mcp_tools[tname]
                        kind = "other"
                        kiro_meta = {
                            "toolName": mt["tool"],
                            "mcpServer": mt["server"],
                            "mcpTool": f"@{mt['server']}/{mt['tool']}",
                        }
                    else:
                        kind = (
                            "execute"
                            if tname == "execute_bash"
                            else ("edit" if tname == "fs_write" else "read")
                        )
                        kiro_meta = {
                            "toolId": tname,
                            "toolName": tname,
                            **(
                                {"command": str(targs.get("command") or "")}
                                if tname == "execute_bash"
                                else {}
                            ),
                        }

                    await self._notify_update(
                        session_id,
                        {
                            "sessionUpdate": "tool_call",
                            "toolCallId": tid,
                            "title": tname,
                            "kind": kind,
                            "status": "pending",
                            "rawInput": targs,
                            "_meta": {"kiro": kiro_meta},
                        },
                    )
                    approved = (not sess.zero_tools) and await self._ask_permission(
                        sess,
                        tc_id=tid,
                        title=tname,
                        kind=kind,
                        raw_input=targs,
                        kiro_meta=kiro_meta,
                    )
                    if not approved:
                        result_str = "Tool execution denied by Aj Crew security policy or user."
                        status_str = "failed"
                    else:
                        try:
                            if is_mcp:
                                mt = sess.mcp_tools[tname]
                                result_str = await sess.mcp_bridge.call_tool(
                                    mt["server"], mt["tool"], targs
                                )
                            else:
                                result_str = await execute_builtin_tool(tname, targs, cwd=sess.cwd)
                            status_str = "completed"
                        except Exception as exc:
                            result_str = f"Tool error: {exc}"
                            status_str = "failed"

                    await self._notify_update(
                        session_id,
                        {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": tid,
                            "status": status_str,
                            "content": [
                                {"type": "content", "content": {"type": "text", "text": result_str}}
                            ],
                            "rawOutput": {"output": result_str},
                        },
                    )
                    sess.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tid,
                            "name": tname,
                            "content": result_str,
                        }
                    )

            self._persist_session(sess)
            await self._send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "stopReason": "end_turn",
                        "usage": {"inputTokens": total_in, "outputTokens": total_out},
                    },
                }
            )
        except Exception as exc:
            await self._send_frame(
                {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}}
            )

    async def dispatch_frame(self, msg: dict[str, Any]) -> None:
        if "method" not in msg and "id" in msg:
            fut = self._pending_client_reqs.pop(msg["id"], None)
            if fut is not None and not fut.done():
                fut.set_result(msg)
            return

        method = str(msg.get("method") or "")
        req_id = msg.get("id")
        raw_params = msg.get("params")
        params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}

        if method == "initialize":
            await self._send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": 1,
                        "agentInfo": {"name": "aj-crew-native", "version": NATIVE_ENGINE_VERSION},
                        "agentCapabilities": {
                            "loadSession": True,
                            "mcpCapabilities": {"http": True, "sse": False},
                            "sessionCapabilities": {"close": {}},
                        },
                    },
                }
            )
            return

        if method == "session/new":
            sid = f"native-{uuid.uuid4().hex[:16]}"
            res = await self._setup_session(sid, params)
            await self._send_frame({"jsonrpc": "2.0", "id": req_id, "result": res})
            return

        if method == "session/load":
            sid = str(params.get("sessionId") or "")
            restored = self._load_persisted_messages(sid)
            if restored is None:
                await self._send_frame(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32603, "message": "Session not found"},
                    }
                )
                return
            res = await self._setup_session(sid, params, restored_msgs=restored)
            await self._send_frame({"jsonrpc": "2.0", "id": req_id, "result": res})
            return

        if method == "session/close":
            sid = str(params.get("sessionId") or "")
            popped = self._sessions.pop(sid, None)
            if popped is not None:
                self._persist_session(popped)
                await popped.mcp_bridge.close_all()
            await self._send_frame({"jsonrpc": "2.0", "id": req_id, "result": {}})
            return

        if method == "session/set_mode":
            sid = str(params.get("sessionId") or "")
            mode_id = str(params.get("modeId") or "")
            sess = self._sessions.get(sid)
            if sess is None:
                await self._send_frame(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32603, "message": "Session not found"},
                    }
                )
                return
            sess.active_mode = mode_id
            self._apply_agent_tool_filter(sess)
            await self._send_frame({"jsonrpc": "2.0", "id": req_id, "result": {}})
            return

        if method == "session/set_config_option":
            sid = str(params.get("sessionId") or "")
            sess = self._sessions.get(sid)
            if sess is None:
                await self._send_frame(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32603, "message": "Session not found"},
                    }
                )
                return
            cid = str(params.get("configId") or "")
            val = str(params.get("value") or "")
            if cid == "model":
                sess.selected_model = val
            elif cid in ("effort", "effortLevel"):
                sess.selected_effort = val
            await self._send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"configOptions": self._config_options(sess)},
                }
            )
            return

        if method == "session/cancel":
            sid = str(params.get("sessionId") or "")
            sess = self._sessions.get(sid)
            if sess is not None:
                sess.cancel_event.set()
            if req_id is not None:
                await self._send_frame({"jsonrpc": "2.0", "id": req_id, "result": {}})
            return

        if method == "_session/steer":
            sid = str(params.get("sessionId") or "")
            sess = self._sessions.get(sid)
            text = str(params.get("message") or params.get("text") or "")
            if sess is not None and text:
                sess.steer_queue.append(text)
            if req_id is not None:
                await self._send_frame({"jsonrpc": "2.0", "id": req_id, "result": {"queued": True}})
            return

        if method == "session/prompt":
            asyncio.create_task(self._handle_prompt(req_id, params))
            return

        if req_id is not None:
            await self._send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )


def _consume_one_time_keys_file() -> dict[str, dict[str, Any]]:
    path = os.environ.pop(KEYS_FILE_ENV, "")
    if not path:
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, str):
                    try:
                        parsed = json.loads(v)
                        if isinstance(parsed, dict):
                            out[str(k)] = parsed
                    except json.JSONDecodeError:
                        pass
    except Exception:
        logger.warning("Failed consuming native keys file", exc_info=True)
    finally:
        discard_keys_file(path)
    return out


async def run_stdio_server() -> None:
    bundle = _consume_one_time_keys_file()
    server = NativeAcpServer(bundle)
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            msg = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict):
            await server.dispatch_frame(msg)
