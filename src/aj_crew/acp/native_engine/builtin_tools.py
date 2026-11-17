"""Built-in workspace tools (`fs_read`, `fs_write`, `grep`, `glob`, `execute_bash`).

Every built-in call goes through the session's ``request_permission`` check in
``server.py`` first, so ``HookManager.on_tool_call`` (``POLICY ∩ PROFILE``,
``is_denied``, ``is_sensitive_path``, ``is_sensitive_bash_command``) gates it
before any disk or process side effect runs.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import sys
from pathlib import Path
from typing import Any

from aj_crew import sandbox

BUILTIN_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "fs_read",
        "description": "Read a UTF-8 text file from disk.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path (relative to cwd or absolute).",
                },
                "start_line": {"type": "integer", "description": "1-based start line (optional)."},
                "end_line": {
                    "type": "integer",
                    "description": "1-based inclusive end line (optional).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "fs_write",
        "description": "Write UTF-8 text content to a file, creating parent directories if needed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Target file path."},
                "content": {"type": "string", "description": "Full UTF-8 content to write."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "glob",
        "description": "Find files under cwd matching a glob pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern such as '**/*.py'."},
                "path": {"type": "string", "description": "Optional base directory."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep",
        "description": "Search UTF-8 text files for a substring or regex pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Substring or regex to match."},
                "path": {"type": "string", "description": "Optional directory or file to search."},
                "include": {"type": "string", "description": "Optional filename glob filter."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "execute_bash",
        "description": "Execute a shell command in the session working directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."},
                "timeout_secs": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 60).",
                },
            },
            "required": ["command"],
        },
    },
]

READ_ONLY_BUILTINS = frozenset({"fs_read", "glob", "grep"})


def _resolve_target(cwd: str, raw_path: str) -> Path:
    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = Path(cwd) / p
    return p.resolve()


async def execute_builtin_tool(name: str, args: dict[str, Any], *, cwd: str) -> str:
    """Run one approved built-in tool call and return bounded UTF-8 text output."""
    if name == "fs_read":
        target = await asyncio.to_thread(_resolve_target, cwd, str(args.get("path") or ""))
        if not target.is_file():
            return f"Error: file not found: {target}"
        text = await asyncio.to_thread(target.read_text, encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(1, int(args.get("start_line") or 1))
        end = min(len(lines), int(args.get("end_line") or min(len(lines), start + 399)))
        numbered = [f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1)]
        return "\n".join(numbered)[:32000]

    if name == "fs_write":
        target = await asyncio.to_thread(_resolve_target, cwd, str(args.get("path") or ""))
        content = str(args.get("content") or "")

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        await asyncio.to_thread(_write)
        return f"Wrote {len(content)} chars to {target}"

    if name == "glob":
        base = await asyncio.to_thread(_resolve_target, cwd, str(args.get("path") or "."))
        pattern = str(args.get("pattern") or "*")

        def _glob() -> list[str]:
            matches: list[str] = []
            for p in base.glob(pattern):
                if ".git" in p.parts or "node_modules" in p.parts:
                    continue
                matches.append(str(p))
                if len(matches) >= 200:
                    break
            return matches

        found = await asyncio.to_thread(_glob)
        return "\n".join(found) if found else "(no matches)"

    if name == "grep":
        import re

        base = await asyncio.to_thread(_resolve_target, cwd, str(args.get("path") or "."))
        pat_str = str(args.get("pattern") or "")
        inc = str(args.get("include") or "")
        try:
            rx = re.compile(pat_str)
        except re.error:
            rx = re.compile(re.escape(pat_str))

        def _grep() -> list[str]:
            hits: list[str] = []
            files = [base] if base.is_file() else list(base.rglob("*"))
            for fp in files:
                if not fp.is_file() or ".git" in fp.parts or "node_modules" in fp.parts:
                    continue
                if inc and not fnmatch.fnmatch(fp.name, inc):
                    continue
                try:
                    if fp.stat().st_size > 1_000_000:
                        continue
                    for lineno, line in enumerate(
                        fp.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
                    ):
                        if rx.search(line):
                            hits.append(f"{fp}:{lineno}:{line[:240]}")
                            if len(hits) >= 150:
                                return hits
                except OSError:
                    continue
            return hits

        found = await asyncio.to_thread(_grep)
        return "\n".join(found) if found else "(no matches)"

    if name == "execute_bash":
        cmd = str(args.get("command") or "").strip()
        if not cmd:
            return "Error: empty command"
        timeout_s = max(1, min(300, int(args.get("timeout_secs") or 60)))
        if sys.platform == "win32":
            raw_argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
        else:
            raw_argv = ["bash", "-lc", cmd]
        scrubbed_env = sandbox.scrub_agent_subprocess_env(dict(os.environ))
        try:
            wrapped_argv, _backend = sandbox.wrap_argv(raw_argv, exec_cwd=cwd, is_kiro_cli=False)
        except Exception:
            wrapped_argv = raw_argv
        proc = await asyncio.create_subprocess_exec(
            *wrapped_argv,
            cwd=cwd,
            env=scrubbed_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Command timed out after {timeout_s}s"
        output = out_bytes.decode("utf-8", errors="replace")[:32000]
        return f"Exit code {proc.returncode}\n{output}".strip()

    return f"Unknown built-in tool: {name}"
