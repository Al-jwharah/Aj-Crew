"""Lightweight stdio & HTTP MCP client bridge for ``native_engine`` sessions."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from aj_crew import sandbox

logger = logging.getLogger(__name__)


@dataclass
class StdioMcpConnection:
    name: str
    proc: asyncio.subprocess.Process
    tools: list[dict[str, Any]] = field(default_factory=list)
    _next_id: int = 1
    _pending: dict[int, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    _reader_task: asyncio.Task[None] | None = None

    async def start_reader(self) -> None:
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                req_id = msg.get("id")
                if isinstance(req_id, int) and req_id in self._pending:
                    fut = self._pending.pop(req_id)
                    if not fut.done():
                        fut.set_result(msg)
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError(f"MCP server {self.name} closed"))
            self._pending.clear()

    async def request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 30.0
    ) -> dict[str, Any]:
        if self.proc.stdin is None:
            raise RuntimeError(f"MCP server {self.name} has no stdin")
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = fut
        payload = (
            json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
            + "\n"
        )
        self.proc.stdin.write(payload.encode("utf-8"))
        await self.proc.stdin.drain()
        resp = await asyncio.wait_for(fut, timeout=timeout)
        if "error" in resp:
            raise RuntimeError(str(resp["error"]))
        res = resp.get("result")
        return res if isinstance(res, dict) else {}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self.proc.stdin is None:
            return
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n"
        self.proc.stdin.write(payload.encode("utf-8"))
        await self.proc.stdin.drain()

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass


class SessionMcpBridge:
    """Manages stdio and HTTP MCP server connections for one ACP session."""

    def __init__(self) -> None:
        self._stdio: dict[str, StdioMcpConnection] = {}
        self._http: dict[str, tuple[str, dict[str, str], list[dict[str, Any]]]] = {}
        self.status_by_server: dict[str, str] = {}

    async def connect_all(
        self,
        servers: dict[str, dict[str, Any]],
        *,
        cwd: str,
        excluded_tags: set[str],
    ) -> list[dict[str, Any]]:
        """Connect declared MCP servers and return filtered tool definitions."""
        exposed: list[dict[str, Any]] = []
        for sname, cfg in servers.items():
            if not isinstance(cfg, dict) or cfg.get("disabled") is True:
                continue
            if f"@{sname}" in excluded_tags:
                continue
            try:
                if cfg.get("url"):
                    tools = await self._connect_http(sname, cfg)
                elif cfg.get("command"):
                    tools = await self._connect_stdio(sname, cfg, cwd=cwd)
                else:
                    continue
                self.status_by_server[sname] = "ready"
                disabled_list = set(cfg.get("disabledTools") or [])
                for t in tools:
                    tname = str(t.get("name") or "")
                    if not tname or tname in disabled_list or f"@{sname}/{tname}" in excluded_tags:
                        continue
                    exposed.append(
                        {
                            "qualified_name": f"mcp__{sname}__{tname}",
                            "server": sname,
                            "tool": tname,
                            "description": str(t.get("description") or ""),
                            "inputSchema": t.get("inputSchema")
                            or {"type": "object", "properties": {}},
                        }
                    )
            except Exception as exc:
                logger.warning("Native MCP connect failed for %r: %s", sname, exc)
                self.status_by_server[sname] = "failed"
        return exposed

    async def _connect_stdio(
        self, sname: str, cfg: dict[str, Any], *, cwd: str
    ) -> list[dict[str, Any]]:
        cmd = str(cfg["command"])
        args = [str(a) for a in (cfg.get("args") or [])]
        base_env = sandbox.scrub_agent_subprocess_env(dict(os.environ))
        env_map = cfg.get("env")
        if isinstance(env_map, dict):
            for k, v in env_map.items():
                if isinstance(k, str) and isinstance(v, str):
                    base_env[k] = v
        elif isinstance(env_map, list):
            for item in env_map:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    base_env[item["name"]] = str(item.get("value") or "")
        proc = await asyncio.create_subprocess_exec(
            cmd,
            *args,
            cwd=cwd if os.path.isdir(cwd) else None,
            env=base_env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        conn = StdioMcpConnection(name=sname, proc=proc)
        await conn.start_reader()
        await conn.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "aj-crew-native", "version": "1.0.0"},
            },
            timeout=20.0,
        )
        await conn.notify("notifications/initialized", {})
        res = await conn.request("tools/list", {}, timeout=20.0)
        tools = [t for t in (res.get("tools") or []) if isinstance(t, dict)]
        conn.tools = tools
        self._stdio[sname] = conn
        return tools

    async def _connect_http(self, sname: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        url = str(cfg["url"])
        headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        raw_headers = cfg.get("headers")
        if isinstance(raw_headers, dict):
            for k, v in raw_headers.items():
                headers[str(k)] = str(v)
        elif isinstance(raw_headers, list):
            for item in raw_headers:
                if isinstance(item, dict) and item.get("name"):
                    headers[str(item["name"])] = str(item.get("value") or "")
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "aj-crew-native", "version": "1.0.0"},
                    },
                },
            ) as _:
                pass
            async with session.post(
                url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ) as resp:
                body = await resp.json(content_type=None)
                res = body.get("result") if isinstance(body, dict) else {}
                tools = [t for t in ((res or {}).get("tools") or []) if isinstance(t, dict)]
        self._http[sname] = (url, headers, tools)
        return tools

    async def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> str:
        """Invoke *tool* on *server* and format its content blocks as text."""
        if server in self._stdio:
            res = await self._stdio[server].request(
                "tools/call",
                {"name": tool, "arguments": arguments},
                timeout=180.0,
            )
        elif server in self._http:
            url, headers, _ = self._http[server]
            timeout = aiohttp.ClientTimeout(total=180)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": tool, "arguments": arguments},
                    },
                ) as resp:
                    body = await resp.json(content_type=None)
                    res = (body.get("result") if isinstance(body, dict) else None) or {}
        else:
            return f"Error: MCP server {server!r} is not connected"

        blocks = res.get("content") or []
        parts: list[str] = []
        if isinstance(blocks, list):
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(str(b.get("text") or ""))
                elif isinstance(b, dict):
                    parts.append(json.dumps(b))
        return "\n".join(parts) if parts else json.dumps(res)

    async def close_all(self) -> None:
        for conn in list(self._stdio.values()):
            await conn.close()
        self._stdio.clear()
        self._http.clear()
