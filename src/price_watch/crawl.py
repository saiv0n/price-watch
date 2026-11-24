from __future__ import annotations

import logging

from .config import Config
from .extract import extract, next_page

log = logging.getLogger(__name__)


def crawl(cfg: Config, fetcher) -> list[dict]:
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
