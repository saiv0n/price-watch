from __future__ import annotations

import argparse
import json
import logging
import sys

from . import __version__, config, export, notify
from .crawl import add_details, crawl
from .fetch import BrowserFetcher, Fetcher
from .store import Store


def _fetcher(cfg):
    cls = BrowserFetcher if cfg.render_js else Fetcher
    return cls(user_agent=cfg.user_agent, delay=cfg.delay, timeout=cfg.timeout,
               respect_robots=cfg.respect_robots)


def cmd_run(args) -> int:
    cfg = config.load(args.config)
    f = _fetcher(cfg)
    try:
        rows = crawl(cfg, f)
    finally:
        f.close()
    if not rows:
        print("no items scraped", file=sys.stderr)
        return 1

    store = Store(args.db)
    _, changes, new = store.save_run(cfg.name, rows, cfg.key)
    store.close()

    drops = [c for c in changes if c.percent <= -cfg.drop_percent and c.percent < 0]
    print(f"{len(rows)} items, {len(new)} new, {len(changes)} price changes, {len(drops)} drops")
    for c in changes:
        print(f"  {c.percent:+6.1f}%  {c.old:g} -> {c.new:g}  {c.title}")
    if drops:
        notify.send(cfg.notify, notify.format_drops(cfg.name, drops))
    if args.out:
        print(f"wrote {export.write(rows, args.out)}")
    return 0


def cmd_test(args) -> int:
    cfg = config.load(args.config)
    cfg.start_urls = [args.url or cfg.start_urls[0]]
    cfg.max_pages = 1
    # detail pages only for the items we print, not the whole first page
    detail, cfg.detail = cfg.detail, None
    f = _fetcher(cfg)
    try:
        rows = crawl(cfg, f)
        if detail:
            cfg.detail = detail
            add_details(cfg, f, rows[: args.limit])
    finally:
        f.close()
    print(f"{len(rows)} items on {cfg.start_urls[0]}")
    for r in rows[: args.limit]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    shown = rows[: args.limit]
    empty = [k for k in (shown[0] if shown else {}) if all(r.get(k) is None for r in shown)]
    if empty:
        print(f"warning: these fields were empty on every item: {', '.join(empty)}", file=sys.stderr)
    return 0 if rows else 1


def cmd_export(args) -> int:
    cfg = config.load(args.config)
    store = Store(args.db)
    rows = store.rows(cfg.name)
    store.close()
    if not rows:
        print("nothing stored yet, run first", file=sys.stderr)
        return 1
    print(f"wrote {export.write(rows, args.out)} ({len(rows)} rows)")
    return 0


def cmd_history(args) -> int:
    cfg = config.load(args.config)
    store = Store(args.db)
    hist = store.history(cfg.name, args.key)
    store.close()
    for seen, price in hist:
        print(f"{seen}  {price}")
    return 0 if hist else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="price-watch", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--db", default="price-watch.db", help="sqlite file for price history")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="crawl, store prices and alert on drops")
    r.add_argument("config")
    r.add_argument("-o", "--out", help="also export this run to .csv, .xlsx or .json")
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("test", help="fetch one page and show what the selectors extract")
    t.add_argument("config")
    t.add_argument("--url")
    t.add_argument("-n", "--limit", type=int, default=3)
    t.set_defaults(func=cmd_test)

    e = sub.add_parser("export", help="export the latest stored run")
    e.add_argument("config")
    e.add_argument("out")
    e.set_defaults(func=cmd_export)

    h = sub.add_parser("history", help="price history of one item")
    h.add_argument("config")
    h.add_argument("key")
    h.set_defaults(func=cmd_history)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
