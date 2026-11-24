from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .config import FieldSpec

_NUM = re.compile(r"\d[\d.,\s ']*")


def parse_price(text: str | None) -> float | None:
    """Turn '£51.77', '1.299,90 TL', '$1,299.00' or '12 499 ₽' into a float."""
    if not text:
        return None
    m = _NUM.search(text)
    if not m:
        return None
    s = re.sub(r"[\s ']", "", m.group()).rstrip(".,")
    if "," in s and "." in s:
        # whichever separator comes last is the decimal one
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) != 3 else s.replace(",", "")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.rpartition(".")[2]) == 3):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _value(node: Tag, spec: FieldSpec, base_url: str):
    el = node.select_one(spec.css) if spec.css else node
    if el is None:
        return spec.default
    if spec.attr:
        raw = el.get(spec.attr)
        raw = " ".join(raw) if isinstance(raw, list) else raw
    else:
        raw = el.get_text(" ", strip=True)
    if raw is None:
        return spec.default
    if spec.re:
        m = re.search(spec.re, raw)
        if not m:
            return spec.default
        raw = m.group(1) if m.groups() else m.group()
    if spec.map is not None:
        return spec.map.get(raw, spec.default)

    match spec.type:
        case "price":
            return parse_price(raw)
        case "int":
            m = re.search(r"-?\d+", raw.replace(",", "").replace(".", ""))
            return int(m.group()) if m else spec.default
        case "url":
            return urljoin(base_url, raw)
        case "bool":
            return bool(raw.strip())
        case _:
            return " ".join(raw.split())


def extract(html: str, item_css: str, fields: dict[str, FieldSpec], base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for node in soup.select(item_css):
        rows.append({name: _value(node, spec, base_url) for name, spec in fields.items()})
    return rows


def next_page(html: str, css: str | None, base_url: str) -> str | None:
    if not css:
        return None
    el = BeautifulSoup(html, "lxml").select_one(css)
    href = el.get("href") if el else None
    return urljoin(base_url, href) if href else None
