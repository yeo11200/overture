"""Start `symphony unified` at login (macOS launchd).

The agent runs the current Python interpreter directly: macOS grants folder
access (e.g. ~/Documents) per executable, and a shell wrapper launched by
launchd is the one that gets blocked.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

LABEL = "dev.oh-my-symphony.unified"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / "Library" / "Logs" / "symphony-unified.log"


class AutostartError(RuntimeError):
    pass


def _symphony_script() -> str:
    found = shutil.which("symphony")
    if found:
        return found
    sibling = Path(sys.executable).parent / "symphony"
    if sibling.exists():
        return str(sibling)
    raise AutostartError("cannot find the `symphony` script; install the package first")


def plist_xml(
    *,
    python: str,
    script: str,
    port: int,
    path_env: str,
    log: Path = LOG,
    extra_args: list[str] | None = None,
) -> str:
    args = "".join(
        f"\n    <string>{escape(a)}</string>"
        for a in (python, script, "unified", "--port", str(port), *(extra_args or []))
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>{args}
  </array>
  <key>WorkingDirectory</key><string>{escape(str(Path.home()))}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>{escape(path_env)}</string>
    <key>HOME</key><string>{escape(str(Path.home()))}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>{escape(str(log))}</string>
  <key>StandardErrorPath</key><string>{escape(str(log))}</string>
</dict>
</plist>
"""


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _require_macos() -> None:
    if sys.platform != "darwin":
        raise AutostartError("autostart is only supported on macOS (launchd) for now")


def install_autostart(port: int = 8787, extra_args: list[str] | None = None) -> Path:
    _require_macos()
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_text(
        plist_xml(
            python=sys.executable,
            script=_symphony_script(),
            port=port,
            path_env=os.environ.get("PATH", "/usr/bin:/bin"),
            extra_args=extra_args,
        ),
        encoding="utf-8",
    )
    _launchctl("bootout", f"{_domain()}/{LABEL}")  # replace a previous version
    result = _launchctl("bootstrap", _domain(), str(PLIST))
    if result.returncode != 0:
        raise AutostartError(result.stderr.strip() or "launchctl bootstrap failed")
    return PLIST


def uninstall_autostart() -> bool:
    _require_macos()
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    if PLIST.exists():
        PLIST.unlink()
        return True
    return False


def autostart_status() -> str:
    _require_macos()
    result = _launchctl("print", f"{_domain()}/{LABEL}")
    if result.returncode != 0:
        return "not installed"
    state = next(
        (line.split("=", 1)[1].strip() for line in result.stdout.splitlines()
         if line.strip().startswith("state =")),
        "unknown",
    )
    return f"installed ({state}), log: {LOG}"
