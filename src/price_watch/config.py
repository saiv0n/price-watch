from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class FieldSpec:
    css: str
    attr: str | None = None
    type: str = "text"  # text | price | int | url | bool
    re: str | None = None
    map: dict[str, object] | None = None
    default: object = None


@dataclass
class Notify:
    webhook: str | None = None  # Discord or Slack incoming webhook
    telegram_token: str | None = None
    telegram_chat: str | None = None


@dataclass
class Detail:
    """Fields read from each item's own page, merged into the listing row."""
    fields: dict[str, FieldSpec]
    url_field: str = "url"


@dataclass
class Config:
    name: str
    start_urls: list[str]
    item: str | None = None
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    source: str = "html"  # html | shopify
    detail: Detail | None = None
    key: str = "url"
    next_page: str | None = None
    max_pages: int = 50
    delay: float = 1.0
    timeout: float = 20.0
    render_js: bool = False
    respect_robots: bool = True
    user_agent: str = "price-watch/0.1 (+https://github.com/saiv0n/price-watch)"
    drop_percent: float = 0.0
    notify: Notify = field(default_factory=Notify)


_ENV = re.compile(r"\$\{(\w+)\}")


def _expand(value):
    # secrets stay out of the yaml, e.g. webhook: ${DISCORD_WEBHOOK}
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), value) or None
    return value


def _fields(raw: dict) -> dict[str, FieldSpec]:
    out = {}
    for name, spec in (raw or {}).items():
        if isinstance(spec, str):
            spec = {"css": spec}
        out[name] = FieldSpec(**spec)
    return out


def load(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    start = raw.get("start_urls") or [raw["start_url"]]
    source = raw.get("source", "html")
    if source not in ("html", "shopify"):
        raise ValueError(f"unknown source {source!r}, use html or shopify")
    fields = _fields(raw.get("fields"))
    if source == "html":
        if not raw.get("item") or not fields:
            raise ValueError("html sources need 'item' and 'fields'")
        if raw.get("key", "url") not in fields:
            raise ValueError(f"key field {raw.get('key', 'url')!r} is not defined in fields")
    detail = None
    if d := raw.get("detail"):
        detail = Detail(fields=_fields(d["fields"]), url_field=d.get("url_field", "url"))

    n = raw.get("notify") or {}
    notify = Notify(**{k: _expand(v) for k, v in n.items()})
    alerts = raw.get("alerts") or {}
    opts = {k: raw[k] for k in ("key", "next_page", "max_pages", "delay", "timeout",
                                "render_js", "respect_robots", "user_agent") if k in raw}
    return Config(
        name=raw["name"],
        start_urls=start,
        item=raw.get("item"),
        fields=fields,
        source=source,
        detail=detail,
        drop_percent=float(alerts.get("drop_percent", 0)),
        notify=notify,
        **opts,
    )
