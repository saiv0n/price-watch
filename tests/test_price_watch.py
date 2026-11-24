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
    f = FakeFetcher({
        BASE + "index.html": (FIX / "mystery_p1.html").read_text(),
        BASE + "page-2.html": (FIX / "mystery_p2.html").read_text(),
    })
    rows = crawl(cfg, f)
    assert f.calls == [BASE + "index.html", BASE + "page-2.html"]
    assert len(rows) == 32
    assert len({r["url"] for r in rows}) == 32


def test_crawl_stops_at_max_pages(cfg):
    cfg.max_pages = 1
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

    cfg_path = tmp_path / "books.yaml"
    cfg_path.write_text(EXAMPLE.read_text().replace("delay: 1.0", "delay: 0"))
    db = str(tmp_path / "pw.db")
    out = tmp_path / "books.xlsx"

    assert cli.main(["--db", db, "run", str(cfg_path), "-o", str(out)]) == 0
    assert "32 items, 32 new" in capsys.readouterr().out
    assert out.exists() and not hook.called

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
