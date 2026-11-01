"""Launch the Streamlit dashboard on loopback; binding elsewhere needs --allow-remote.

uv run python scripts/run_dashboard.py [--host 127.0.0.1] [--port 8501] [--allow-remote]

The dashboard has no login of its own: anyone who can reach it sees every alert and posting
(with the API key it holds server-side). So it binds 127.0.0.1 unless explicitly told
otherwise, and says so loudly when it is.
"""

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from jobsignal.api.serve import is_loopback

APP_PATH = Path(__file__).resolve().parents[3] / "dashboard" / "app.py"


def main(argv: list[str] | None = None, run: Callable[[list[str]], int] = subprocess.call) -> int:
    parser = argparse.ArgumentParser(description="Serve the JobSignal dashboard (Streamlit).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow a non-loopback --host (the dashboard has no login)",
    )
    args = parser.parse_args(argv)
    if not is_loopback(args.host):
        if not args.allow_remote:
            print(
                f"refusing to bind {args.host!r}: the dashboard has no login. "
                "Pass --allow-remote to expose it anyway.",
                file=sys.stderr,
            )
            return 2
        print(
            f"WARNING: the dashboard has no login; anyone who can reach "
            f"{args.host}:{args.port} sees all data.",
            file=sys.stderr,
        )
    return run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP_PATH),
            "--server.address",
            args.host,
            "--server.port",
            str(args.port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ]
    )
