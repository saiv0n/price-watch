from __future__ import annotations

import logging

import httpx

from .config import Notify
from .store import Change

log = logging.getLogger(__name__)


def format_drops(site: str, drops: list[Change]) -> str:
    lines = [f"Price drops on {site}:"]
    for c in sorted(drops, key=lambda c: c.percent):
        lines.append(f"- {c.title}: {c.old:g} -> {c.new:g} ({c.percent:+.1f}%)\n  {c.key}")
    return "\n".join(lines)


def send(n: Notify, text: str) -> None:
    if n.webhook:
        # Discord reads "content", Slack reads "text"; sending both works for either
        _post(n.webhook, {"content": text[:1900], "text": text})
    if n.telegram_token and n.telegram_chat:
        _post(f"https://api.telegram.org/bot{n.telegram_token}/sendMessage",
              {"chat_id": n.telegram_chat, "text": text[:4000], "disable_web_page_preview": True})


def _post(url: str, payload: dict) -> None:
    try:
        httpx.post(url, json=payload, timeout=15).raise_for_status()
    except httpx.HTTPError as e:
        # a broken webhook should not lose the crawl that was just saved
        log.error("notification failed: %s", e)
