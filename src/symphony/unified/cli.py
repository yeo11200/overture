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
from .graph import GraphNotes
from .hooks import TARGET_FILES, hooks_installed, install_hooks, uninstall_hooks
from .sessions import SessionStore
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

    sessions = SessionStore(
        lambda: [rt.project for rt in supervisor.runtimes()],
        watch_root=Path(args.watch).expanduser() if args.watch else None,
        ignore_roots=[Path.home() / "symphony_workspaces", Path("/Applications")],
    )
    graph = GraphNotes(projects_file().parent / "unified-graph.json")
    scanner_task = asyncio.create_task(
        sessions.run_scanner(on_scan=graph.prune), name="unified-sessions"
    )

    runner, port = await run_unified_app(
        build_unified_app(supervisor, discovery=discovery, sessions=sessions, graph=graph),
        args.host,
        args.port,
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
        scanner_task.cancel()
        await runner.cleanup()
        await supervisor.stop_all()
    return 0


def _hooks_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="symphony unified hooks",
        description="Manage the Claude Code hooks that feed the session monitor "
        "(~/.claude/settings.json).",
    )
    parser.add_argument("action", choices=["install", "uninstall", "status"])
    parser.add_argument("--port", type=int, default=8787)
    tool = parser.add_mutually_exclusive_group()
    tool.add_argument("--claude", dest="target", action="store_const", const="claude")
    tool.add_argument("--codex", dest="target", action="store_const", const="codex")
    parser.set_defaults(target="claude")
    args = parser.parse_args(argv)
    path = TARGET_FILES[args.target]
    if args.action == "install":
        added = install_hooks(args.port, path, args.target)
        print(f"{args.target} hooks installed: {', '.join(added) or 'already present'}")
        if added and args.target == "codex":
            print("Codex runs new hooks only after you approve them: open Codex and run /hooks.")
    elif args.action == "uninstall":
        removed = uninstall_hooks(path, args.target)
        print(f"{args.target} hooks removed: {', '.join(removed) or 'nothing to remove'}")
    else:
        print(f"{args.target} hooks: {', '.join(hooks_installed(path, args.target)) or 'none'}")
    return 0


def _autostart_main(argv: list[str]) -> int:
    from .autostart import AutostartError, autostart_status, install_autostart, uninstall_autostart

    parser = argparse.ArgumentParser(
        prog="symphony unified autostart",
        description="Run `symphony unified` at login (macOS launchd).",
    )
    parser.add_argument("action", choices=["install", "uninstall", "status"])
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--watch", default="", help="folder whose new git repos auto-register")
    args = parser.parse_args(argv)
    try:
        if args.action == "install":
            extra = ["--watch", str(Path(args.watch).expanduser())] if args.watch else []
            print(f"autostart installed: {install_autostart(args.port, extra)}")
            print(f"board: http://127.0.0.1:{args.port}/")
        elif args.action == "uninstall":
            print("autostart removed" if uninstall_autostart() else "autostart was not installed")
        else:
            print(autostart_status())
    except AutostartError as exc:
        print(f"symphony unified autostart: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv and argv[0] == "hooks":
        return _hooks_main(argv[1:])
    if argv and argv[0] == "autostart":
        return _autostart_main(argv[1:])
    parser = argparse.ArgumentParser(
        prog="symphony unified",
        description="Run every registered project in one process and serve one board.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--watch",
        default="",
        help="auto-register new git repos under this folder (default: off)",
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
