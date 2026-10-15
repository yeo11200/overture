"""`symphony unified` — every registered project in one process on one port."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path

from ..logging import configure_logging
from ..projects import ProjectRegistry, projects_file
from .api import build_unified_app, run_unified_app
from .discovery import Discovery
from .supervisor import Supervisor

DEFAULT_EXCLUDE = "oh-my-symphony"


async def _serve(args: argparse.Namespace) -> int:
    registry = ProjectRegistry()
    supervisor = Supervisor(registry, port=args.port)
    await supervisor.start_all()
    discovery = None
    discovery_task = None
    if args.watch:
        discovery = Discovery(
            Path(args.watch),
            registry=registry,
            supervisor=supervisor,
            exclude={name.strip() for name in args.exclude.split(",") if name.strip()},
            failures_path=projects_file().parent / "unified-failures.json",
        )
        discovery_task = asyncio.create_task(discovery.run(), name="unified-discovery")

    runner, port = await run_unified_app(
        build_unified_app(supervisor, discovery=discovery), args.host, args.port
    )
    host = "127.0.0.1" if args.host in {"", "0.0.0.0", "::"} else args.host
    hosted = sum(rt.orchestrator is not None for rt in supervisor.runtimes())
    print(
        f"symphony: unified board at http://{host}:{port}/ "
        f"({hosted}/{len(supervisor.runtimes())} projects hosted)",
        file=sys.stderr,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        if discovery_task is not None:
            discovery_task.cancel()
        await runner.cleanup()
        await supervisor.stop_all()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="symphony unified",
        description="Run every registered project in one process and serve one board.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--watch",
        default=str(Path.home() / "Documents" / "_shin"),
        help="auto-register new git repos under this folder ('' disables)",
    )
    parser.add_argument(
        "--exclude",
        default=DEFAULT_EXCLUDE,
        help="comma-separated folder names discovery must skip",
    )
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    try:
        return asyncio.run(_serve(args))
    except OSError as exc:
        print(f"symphony unified: {exc}", file=sys.stderr)
        return 1
