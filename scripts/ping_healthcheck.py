"""Pings healthchecks.io to signal a successful full pipeline run — the
"silent failure" layer of this project's observability (see docs/adr/0003):
it catches a pipeline that should have run and didn't (e.g. a GitHub
Actions cron trigger that never fires), which neither the Telegram
failure alert nor Elementary's data-quality checks can detect, since both
only run when the pipeline itself actually executes.

Call this only at the very end of a fully successful run — a missed or
late ping is exactly the signal healthchecks.io alerts on.

Standalone script: see notify_telegram.py's docstring for why these
scripts avoid importing the `ingestion` package.

Usage:
    python scripts/ping_healthcheck.py

Required environment variable:
    HEALTHCHECK_URL   this check's unique ping URL, from healthchecks.io
"""

from __future__ import annotations

import os
import sys

import httpx


def ping(url: str, *, timeout: float = 10.0) -> None:
    response = httpx.get(url, timeout=timeout)
    response.raise_for_status()


def main() -> int:
    url = os.environ.get("HEALTHCHECK_URL")
    if not url:
        print("HEALTHCHECK_URL must be set.", file=sys.stderr)
        return 1

    try:
        ping(url)
    except httpx.HTTPError as exc:
        print(f"Failed to ping healthchecks.io: {exc}", file=sys.stderr)
        return 1

    print("healthchecks.io ping sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
