"""Run the API with uvicorn. Binding beyond loopback requires JOBSIGNAL_API_KEY.

uv run python scripts/run_api.py [--host 127.0.0.1] [--port 8000]
"""

import argparse
import ipaddress
import logging

import uvicorn

from jobsignal.api.app import create_app
from jobsignal.config import get_settings
from jobsignal.logger import setup_logging

logger = logging.getLogger(__name__)


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # hostnames other than localhost may resolve anywhere


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the read-only JobSignal API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    setup_logging()
    if not is_loopback(args.host) and get_settings().api_key is None:
        logger.error(
            "refusing to bind %r without JOBSIGNAL_API_KEY: the API would be reachable from "
            "the network unauthenticated",
            args.host,
        )
        return 2
    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0
