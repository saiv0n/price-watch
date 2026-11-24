from pathlib import Path

import httpx
import openpyxl
import pytest
import respx

from price_watch import cli, config, export
from price_watch.crawl import crawl
from price_watch.extract import extract, parse_price
from price_watch.fetch import Fetcher
from price_watch.store import Store

FIX = Path(__file__).parent / "fixtures"
EXAMPLE = Path(__file__).parents[1] / "examples" / "books.yaml"
BASE = "https://books.toscrape.com/catalogue/category/books/mystery_3/"


@pytest.mark.parametrize("text,expected", [
    ("£51.77", 51.77),
    ("$1,299.00", 1299.0),
    ("1.299,90 TL", 1299.9),
    ("₺ 12.499", 12499.0),
    ("12 499 ₽", 12499.0),
    ("€ 9,95", 9.95),
    ("CHF 1'250.50", 1250.5),
    ("1,299", 1299.0),
    ("Price: 7", 7.0),
    ("out of stock", None),
    (None, None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.fixture
def cfg():
    return config.load(EXAMPLE)


def test_extract_fixture(cfg):
    rows = extract((FIX / "mystery_p1.html").read_text(), cfg.item, cfg.fields, BASE + "index.html")
    assert len(rows) == 20
    first = rows[0]
    assert first["title"] == "Sharp Objects"
    assert first["price"] == 47.82
    assert first["in_stock"] is True
    assert first["rating"] == 4
    assert first["url"] == "https://books.toscrape.com/catalogue/sharp-objects_997/index.html"
    assert first["image"].startswith("https://books.toscrape.com/media/")


def test_missing_key_field_is_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("name: x\nstart_url: http://x\nitem: div\nfields:\n  title: h1\n")
    with pytest.raises(ValueError, match="key field"):
        config.load(p)


def test_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOK", "https://hooks.example/abc")
    p = tmp_path / "c.yaml"
    p.write_text("name: x\nstart_url: http://x\nitem: div\nfields:\n  url: a\n"
                 "notify:\n  webhook: ${HOOK}\n  telegram_token: ${UNSET_VAR}\n")
    c = config.load(p)
    assert c.notify.webhook == "https://hooks.example/abc"
    assert c.notify.telegram_token is None


class FakeFetcher:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url):
        self.calls.append(url)
        return self.pages[url]


def test_crawl_follows_pagination(cfg):
    cfg.detail = None
    f = FakeFetcher({
        BASE + "index.html": (FIX / "mystery_p1.html").read_text(),
        BASE + "page-2.html": (FIX / "mystery_p2.html").read_text(),
    })
    rows = crawl(cfg, f)
    assert f.calls == [BASE + "index.html", BASE + "page-2.html"]
    assert len(rows) == 32
    assert len({r["url"] for r in rows}) == 32


def test_crawl_stops_at_max_pages(cfg):
    cfg.max_pages, cfg.detail = 1, None
    f = FakeFetcher({BASE + "index.html": (FIX / "mystery_p1.html").read_text()})
    assert len(crawl(cfg, f)) == 20


def test_store_detects_changes(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    a = {"url": "a", "title": "A", "price": 10.0}
    b = {"url": "b", "title": "B", "price": 20.0}
    _, changes, new = s.save_run("site", [a, b], "url")
    assert changes == [] and len(new) == 2

    _, changes, new = s.save_run("site", [dict(a, price=8.0), b, {"url": "c", "price": 5.0}], "url")
    assert [(c.key, c.old, c.new) for c in changes] == [("a", 10.0, 8.0)]
    assert changes[0].percent == pytest.approx(-20.0)
    assert [r["url"] for r in new] == ["c"]
    assert [p for _, p in s.history("site", "a")] == [10.0, 8.0]
    assert len(s.rows("site")) == 3


def test_store_ignores_duplicates_and_other_sites(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.save_run("one", [{"url": "a", "price": 1.0}], "url")
    _, changes, new = s.save_run("two", [{"url": "a", "price": 2.0}, {"url": "a", "price": 3.0}], "url")
    assert changes == [] and len(new) == 1
    assert len(s.rows("two")) == 1


@pytest.mark.parametrize("suffix", [".csv", ".json", ".xlsx"])
def test_export(tmp_path, suffix):
    rows = [{"title": "Çay & şeker", "price": 1.5}, {"title": "B", "price": 2.0, "extra": "x"}]
    out = export.write(rows, tmp_path / f"out{suffix}")
    if suffix == ".xlsx":
        ws = openpyxl.load_workbook(out).active
        assert [c.value for c in ws[1]] == ["title", "price", "extra"]
        assert ws["A2"].value == "Çay & şeker"
    else:
        assert "Çay & şeker" in out.read_text(encoding="utf-8-sig")


def test_export_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        export.write([{"a": 1}], tmp_path / "x.txt")


@respx.mock
def test_fetcher_retries_and_respects_robots():
    respx.get("https://shop.test/robots.txt").respond(200, text="User-agent: *\nDisallow: /private\n")
    route = respx.get("https://shop.test/list").mock(side_effect=[
        httpx.Response(503, headers={"Retry-After": "0"}),
        httpx.Response(200, text="ok"),
    ])
    f = Fetcher("test-agent", delay=0)
    assert f.get("https://shop.test/list") == "ok"
    assert route.call_count == 2
    with pytest.raises(Exception, match="private"):
        f.get("https://shop.test/private/x")


@respx.mock
def test_cli_run_end_to_end(tmp_path, monkeypatch, capsys):
    hook = respx.post("https://hooks.test/x").respond(204)
    monkeypatch.setenv("PRICE_WATCH_WEBHOOK", "https://hooks.test/x")
    respx.get("https://books.toscrape.com/robots.txt").respond(404)
    p1 = (FIX / "mystery_p1.html").read_text()
    p2 = (FIX / "mystery_p2.html").read_text()
    respx.get(BASE + "index.html").respond(200, text=p1)
    respx.get(BASE + "page-2.html").respond(200, text=p2)
    detail = respx.get(url__regex=r"/catalogue/[^/]+_\d+/index\.html$").respond(
        200, text=(FIX / "sharp_objects.html").read_text())

    cfg_path = tmp_path / "books.yaml"
    cfg_path.write_text(EXAMPLE.read_text().replace("delay: 1.0", "delay: 0"))
    db = str(tmp_path / "pw.db")
    out = tmp_path / "books.xlsx"

    assert cli.main(["--db", db, "run", str(cfg_path), "-o", str(out)]) == 0
    assert "32 items, 32 new" in capsys.readouterr().out
    assert out.exists() and not hook.called
    assert detail.call_count == 32
    ws = openpyxl.load_workbook(out).active
    header = [c.value for c in ws[1]]
    assert {"upc", "stock", "category", "description"} <= set(header)

    # second run: one book got 10% cheaper, another 2% cheaper (below the 5% alert threshold)
    respx.get(BASE + "index.html").respond(
        200, text=p1.replace("£47.82", "£43.04").replace("£19.63", "£19.24"))
    assert cli.main(["--db", db, "run", str(cfg_path)]) == 0
    out_text = capsys.readouterr().out
    assert "2 price changes, 1 drops" in out_text
    assert hook.call_count == 1
    body = hook.calls[0].request.content.decode()
    assert "Sharp Objects" in body and "-10.0%" in body

    assert cli.main(["--db", db, "history", str(cfg_path),
                     "https://books.toscrape.com/catalogue/sharp-objects_997/index.html"]) == 0
    assert "43.04" in capsys.readouterr().out


def test_detail_page_fields(cfg):
    from price_watch.extract import extract_one

    url = "https://books.toscrape.com/catalogue/sharp-objects_997/index.html"
    row = extract_one((FIX / "sharp_objects.html").read_text(), cfg.detail.fields, url)
    assert row["upc"] == "e00eb4fd7b871a48"
    assert row["stock"] == 20
    assert row["category"] == "Mystery"
    assert row["description"].startswith("WICKED above her hipbone")


def test_detail_failure_keeps_the_row(cfg):
    from price_watch.crawl import add_details

    class Broken:
        def get(self, url):
            raise httpx.ConnectError("boom")

    rows = [{"url": "https://x.test/a", "price": 1.0}]
    add_details(cfg, Broken(), rows)
    assert rows[0]["price"] == 1.0 and "boom" in rows[0]["error"]


def test_shopify_source(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("name: s\nsource: shopify\nstart_url: https://shop.test/collections/sale/\n")
    c = config.load(p)
    pages = {
        "https://shop.test/collections/sale/products.json?limit=250&page=1": (FIX / "shopify_p1.json").read_text(),
        "https://shop.test/collections/sale/products.json?limit=250&page=2": '{"products": []}',
    }
    f = FakeFetcher(pages)
    rows = crawl(c, f)
    assert len(f.calls) == 2
    shoe, tee = rows
    assert shoe == {
        "title": "Wool Runner", "url": "https://shop.test/products/wool-runner",
        "price": 105.0, "compare_at_price": 140.0, "on_sale": True, "available": True,
        "vendor": "Acme", "product_type": "Shoes", "sku": "WR-8", "variants": 2,
        "image": "https://cdn.example/w.jpg",
    }
    assert tee["on_sale"] is False and tee["sku"] is None and tee["image"] is None


def test_shopify_root_url_uses_whole_catalogue(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("name: s\nsource: shopify\nstart_url: https://shop.test/pages/about\nmax_pages: 1\n")
    f = FakeFetcher({"https://shop.test/products.json?limit=250&page=1": '{"products": []}'})
    assert crawl(config.load(p), f) == []


def test_unknown_source_is_rejected(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("name: s\nsource: magento\nstart_url: https://x.test\n")
    with pytest.raises(ValueError, match="unknown source"):
        config.load(p)


def test_google_sheets_export(monkeypatch):
    import sys
    import types

    calls = {}

    class WS:
        def clear(self): calls["clear"] = True
        def update(self, values, start): calls["values"], calls["start"] = values, start
        def freeze(self, rows): calls["freeze"] = rows

    class Book:
        def worksheet(self, name):
            calls["tab"] = name
            return WS()

    class GC:
        def open_by_key(self, key):
            calls["key"] = key
            return Book()

    fake = types.SimpleNamespace(service_account=lambda filename=None: GC(),
                                 WorksheetNotFound=type("WNF", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "gspread", fake)
    url = export.write([{"title": "A", "price": None}], "sheets:abc123/prices")
    assert url == "https://docs.google.com/spreadsheets/d/abc123"
    assert calls["key"] == "abc123" and calls["tab"] == "prices"
    assert calls["values"] == [["title", "price"], ["A", ""]]
