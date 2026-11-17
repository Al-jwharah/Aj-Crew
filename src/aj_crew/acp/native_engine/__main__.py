"""Entrypoint for ``python -m aj_crew.acp.native_engine``."""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    if sys.platform == "win32":
        # Ensure UTF-8 stdio pipes on Windows for ACP JSON-RPC frames.
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            reconf = getattr(stream, "reconfigure", None)
            if callable(reconf):
                reconf(encoding="utf-8", errors="replace")
    from aj_crew.acp.native_engine.server import run_stdio_server

    asyncio.run(run_stdio_server())


if __name__ == "__main__":
    main()
