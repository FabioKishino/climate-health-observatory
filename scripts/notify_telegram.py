"""Sends a pipeline status notification to Telegram — the "operational
failure" layer of this project's observability (see docs/adr/0003): it
catches execution errors (API down, an unhandled exception in code), which
is a different failure mode than a job that silently never runs
(healthchecks.io, ping_healthcheck.py) or one that runs but produces bad
data (Elementary, wired into `dbt build`).

Standalone script: deliberately has no dependency on the `ingestion`
package, so it runs correctly as a plain `python scripts/notify_telegram.py`
from any working directory — unlike the ingestion extract scripts, which
must be run as `python -m ingestion.<module>.extract` from the repo root
for their absolute imports to resolve.

Usage:
    python scripts/notify_telegram.py --status success --message "dbt build passed"
    python scripts/notify_telegram.py --status failure --message "INMET extraction failed"

Required environment variables:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

Optional:
    GITHUB_RUN_NUMBER   included in the message when set (GitHub Actions
                         sets this automatically for every workflow run)
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

_STATUS_EMOJI = {"success": "✅", "failure": "🚨"}
_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def build_message(status: str, message: str, run_number: str | None) -> str:
    emoji = _STATUS_EMOJI[status]
    lines = [f"{emoji} Climate x Health Observatory — pipeline {status.upper()}", message]
    if run_number:
        lines.append(f"GitHub Actions run: #{run_number}")
    return "\n".join(lines)


def send_telegram_message(bot_token: str, chat_id: str, text: str, *, timeout: float = 10.0) -> None:
    url = _TELEGRAM_API_URL.format(token=bot_token)
    response = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=timeout)
    response.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a pipeline status notification to Telegram.")
    parser.add_argument("--status", choices=sorted(_STATUS_EMOJI), required=True)
    parser.add_argument("--message", required=True)
    args = parser.parse_args()

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set.", file=sys.stderr)
        return 1

    run_number = os.environ.get("GITHUB_RUN_NUMBER")
    text = build_message(args.status, args.message, run_number)

    try:
        send_telegram_message(bot_token, chat_id, text)
    except httpx.HTTPError as exc:
        print(f"Failed to send Telegram notification: {exc}", file=sys.stderr)
        return 1

    print("Telegram notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
