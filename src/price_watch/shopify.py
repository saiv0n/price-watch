"""Shopify stores expose their catalogue as JSON, which beats parsing HTML."""
from __future__ import annotations

import json
import logging
from urllib.parse import urlsplit

from .config import Config

log = logging.getLogger(__name__)


def _float(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def product_row(p: dict, origin: str) -> dict:
    variants = p.get("variants") or []
    prices = [x for v in variants if (x := _float(v.get("price"))) is not None]
    compare = [x for v in variants if (x := _float(v.get("compare_at_price"))) is not None]
    images = p.get("images") or []
    price = min(prices) if prices else None
    was = min(compare) if compare else None
    return {
        "title": p.get("title"),
        "url": f"{origin}/products/{p.get('handle')}",
        "price": price,
        "compare_at_price": was,
        "on_sale": bool(price is not None and was and was > price),
        "available": any(v.get("available") for v in variants),
        "vendor": p.get("vendor"),
        "product_type": p.get("product_type"),
        "sku": next((v["sku"] for v in variants if v.get("sku")), None),
        "variants": len(variants),
        "image": images[0].get("src") if images else None,
    }


def crawl_shopify(cfg: Config, fetcher) -> list[dict]:
    rows: list[dict] = []
    for start in cfg.start_urls:
        parts = urlsplit(start)
        origin = f"{parts.scheme}://{parts.netloc}"
        # a /collections/<name> url limits the crawl to that collection
        path = parts.path.rstrip("/") if parts.path.startswith("/collections/") else ""
        for page in range(1, cfg.max_pages + 1):
            data = json.loads(fetcher.get(f"{origin}{path}/products.json?limit=250&page={page}"))
            products = data.get("products") or []
            log.info("shopify page %d: %d products", page, len(products))
            if not products:
                break
            rows.extend(product_row(p, origin) for p in products)
    return rows
