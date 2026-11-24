from __future__ import annotations

import logging

import httpx

from .config import Config
from .extract import extract, extract_one, next_page
from .fetch import BlockedByRobots

log = logging.getLogger(__name__)


def crawl(cfg: Config, fetcher) -> list[dict]:
    if cfg.source == "shopify":
        from .shopify import crawl_shopify
        rows = crawl_shopify(cfg, fetcher)
    else:
        rows = _crawl_listing(cfg, fetcher)
    if cfg.detail:
        add_details(cfg, fetcher, rows)
    return rows


def _crawl_listing(cfg: Config, fetcher) -> list[dict]:
    rows: list[dict] = []
    for start in cfg.start_urls:
        url, pages, visited = start, 0, set()
        while url and pages < cfg.max_pages and url not in visited:
            visited.add(url)
            html = fetcher.get(url)
            found = extract(html, cfg.item, cfg.fields, url)
            log.info("page %d: %s (%d items)", pages + 1, url, len(found))
            if not found:
                log.warning("no items matched %r on %s, check the selector", cfg.item, url)
            rows.extend(found)
            pages += 1
            url = next_page(html, cfg.next_page, url)
    return rows


def add_details(cfg: Config, fetcher, rows: list[dict]) -> None:
    d = cfg.detail
    for i, row in enumerate(rows, 1):
        url = row.get(d.url_field)
        if not url:
            continue
        try:
            row.update(extract_one(fetcher.get(url), d.fields, url))
        except (httpx.HTTPError, BlockedByRobots) as e:
            # one dead product page shouldn't sink a crawl of thousands
            log.warning("detail page failed: %s (%s)", url, e)
            row["error"] = str(e)
        if i % 25 == 0:
            log.info("details: %d/%d", i, len(rows))
