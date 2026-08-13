#!/usr/bin/env python3
"""Build the independent runtime virtualenv (.plugin-venv) for omp-mypai.

Creates a snapshot (non-editable) virtualenv at ``<plugin>/.plugin-venv`` so the
plugin's runtime environment never shares state with the development ``.venv``.
The OMP MCP servers declared in ``.mcp.json`` launch ``./.plugin-venv/bin/python3``
(a plugin-relative path resolved by OMP against the plugin root).

Rebuild whenever the plugin's Python code or dependencies change:
``make installenv``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def system_omp_rpc_src() -> str | None:
    base = Path("/usr/share/oh-my-pi/python/omp-rpc")
    wheels = sorted(base.glob("dist/*.whl"))
    if wheels:
        return str(wheels[0])
    if (base / "pyproject.toml").exists():
        return str(base)
    return None


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    plugin_root = Path(__file__).resolve().parent.parent
    venv_dir = plugin_root / ".plugin-venv"
    src_dir = plugin_root / "src"

    print(f"plugin root: {plugin_root}")
    print(f"runtime venv: {venv_dir}")
    print(f"source:       {src_dir}")

    if venv_dir.exists():
        print(f"removing stale runtime venv: {venv_dir}")
        shutil.rmtree(venv_dir)

    run([sys.executable, "-m", "venv", str(venv_dir)])
    venv_python = venv_dir / "bin" / "python3"

    if shutil.which("uv"):
        installer = ["uv", "pip", "install", "--python", str(venv_python)]
    else:
        installer = [str(venv_python), "-m", "pip", "install"]

    omp_rpc = system_omp_rpc_src()
    if omp_rpc:
        run(installer + [omp_rpc])

    # Snapshot (non-editable) install of the plugin package + declared deps.
    run(installer + [str(src_dir)])

    # Self-check: the two configured MCP entry points must import cleanly.
    run(
        [
            str(venv_python),
            "-c",
            "import mypai_tools, mypai_tools.chat_mcp, mypai_tools.cron_mcp; print('runtime env OK')",
        ]
    )

    print(f"done: {venv_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
