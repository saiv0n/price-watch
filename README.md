# price-watch

Scrape product listings from any shop into CSV, Excel or JSON, keep a price history in SQLite, and get a Discord, Slack or Telegram message when something gets cheaper.

Every site is described by one small YAML file, so adding a new shop means writing selectors, not code.

```
$ price-watch run examples/books.yaml -o books.xlsx
32 items, 32 new, 0 price changes, 0 drops
wrote books.xlsx

# a day later
$ price-watch run examples/books.yaml
32 items, 0 new, 1 price changes, 1 drops
   -10.0%  47.82 -> 43.04  Sharp Objects
```

## What it handles

- Pagination, by following a "next" link until it runs out or hits `max_pages`
- Prices in any common format: `£51.77`, `$1,299.00`, `1.299,90 TL`, `12 499 ₽`, `CHF 1'250.50`
- Relative links and image paths, turned into absolute URLs
- Polite crawling with a delay between requests, retries with backoff on 429/5xx, `Retry-After`, and robots.txt
- JavaScript-rendered shops through headless Chromium (optional, see below)
- Excel output with a frozen header row, filters and sensible column widths
- Secrets like webhook URLs read from environment variables, never stored in the config

## Install

```bash
git clone https://github.com/saiv0n/price-watch
cd price-watch
pip install .
```

For shops that render products with JavaScript:

```bash
pip install '.[js]'
playwright install chromium
```

and set `render_js: true` in the config.

## Configure a site

```yaml
name: books
start_url: https://books.toscrape.com/catalogue/category/books/mystery_3/index.html
item: article.product_pod        # one match per product
key: url                         # field that identifies a product between runs
next_page: li.next a

fields:
  title: {css: h3 a, attr: title}
  url:   {css: h3 a, attr: href, type: url}
  price: {css: .price_color, type: price}
  rating:
    css: p.star-rating
    attr: class
    re: "(One|Two|Three|Four|Five)"
    map: {One: 1, Two: 2, Three: 3, Four: 4, Five: 5}

alerts:
  drop_percent: 5                # only alert on drops of 5% or more

notify:
  webhook: ${PRICE_WATCH_WEBHOOK}
```

Each field takes a CSS selector and optionally `attr` (read an attribute instead of text), `re` (keep the first regex group), `map` (translate values), `default`, and a `type` of `text`, `price`, `int`, `url` or `bool`. A plain string like `title: h1` is shorthand for `{css: h1}`.

Other options: `start_urls` (a list), `max_pages`, `delay`, `timeout`, `user_agent`, `respect_robots`, `render_js`.

Before a full run, check your selectors against one page:

```bash
price-watch test mysite.yaml -n 2
```

It prints the first items it extracted and warns about fields that came back empty on every item.

## Commands

```bash
price-watch run CONFIG [-o out.xlsx]      # crawl, store, alert, optionally export
price-watch test CONFIG [--url URL]       # dry run on one page
price-watch export CONFIG out.csv         # export the last stored run
price-watch history CONFIG ITEM_URL       # price history of one product
```

`--db path` chooses the SQLite file (default `price-watch.db`), `-v` logs every page.

## Notifications

Set any of these and price drops are sent there:

```bash
export PRICE_WATCH_WEBHOOK=https://discord.com/api/webhooks/...   # or a Slack incoming webhook
export TELEGRAM_TOKEN=123456:ABC...
export TELEGRAM_CHAT_ID=123456789
```

A failing webhook is logged and does not throw away the crawl that was just saved.

## Run it on a schedule

With cron, every six hours:

```
0 */6 * * * cd /path/to/price-watch && PRICE_WATCH_WEBHOOK=... price-watch run examples/books.yaml
```

The included [GitHub Actions workflow](.github/workflows/ci.yml) runs the tests; the same setup can run a scheduled crawl and commit the CSV back to the repo if you don't have a server.

## Tests

```bash
uv run pytest
```

The tests run offline against saved pages and mocked HTTP, covering price parsing, pagination, change detection, all three export formats, retries, robots.txt and a full two-run CLI session with a webhook.

## Scraping responsibly

The example targets books.toscrape.com, a site made for scraping practice. For real shops, read their terms, keep the delay reasonable and leave `respect_robots` on.

## License

MIT
