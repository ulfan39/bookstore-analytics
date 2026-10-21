# Bookstore data pipeline

Cleans the STORE1..STORE5 dumps (orders.parquet, users.csv, books.yaml) and computes:
top-5 revenue days, number of real users, number of author sets, most popular
author set, best buyer (all user ids) and the daily revenue series.

## Run

    pip install -r requirements.txt
    python run_all.py <folder with STORE1..STORE5>

Results are written to `results.json` and `STORE*_daily_revenue.csv` in the repository root.

## Cleaning rules

- Prices: 20 spellings (`$ 35`, `30.0USD`, `EUR37.50`, `$57¢50`, `63€50¢`) are parsed
  into amount + currency; EUR -> USD with 1 EUR = 1.2 USD. The unit price is rounded
  to cents first, then `paid_price = quantity * unit_price_usd`.
- Timestamps: ~130 layouts (ISO, `MM/DD/YY`, `DD.MM.YYYY`, `DD-Mon-YYYY`, ctime, 12/24h
  with `A.M./P.M.`) parsed with explicit rules. Slash dates are month-first and dot dates
  are day-first (verified: first number never exceeds 12 for slash, second never for dot).
- `shipping`: `''` and `'NULL'` become missing.
- Duplicate orders are dropped by `id` and by (user, book, quantity, price, timestamp).

## Real users

A person changes at most one of name, address, phone (digits only) or e-mail, so
two records of one person match on at least 3 of the 4 fields. Records are linked
when any 3-field combination is identical and non-missing; connected components
(union-find) are the real users.

## Authors

`books.author` is split on commas into a set of authors. "Most popular" is the author
set with the most sold books (`sum(quantity)`); the per-author ranking is also stored.

## Dashboard and AI assistant

`app.py` (FastAPI) serves the dashboard (`index.html`) and a small API; `bookstore.db`
(SQLite, built by `build_db.py` from the cleaned data) holds all five stores.

- Overview / Revenue tabs: unique users, unique author sets, most popular author,
  best buyer (ids as array), top-5 days, daily revenue chart.
- Books / Users tabs: server-side tables with filters, sorting and paging.
- **Assistant panel** (right side): an LLM with tools (OpenAI-compatible function calling,
  `llm.py`). The model never sees the data and never calculates numbers:
  - `run_sql` (read-only SELECT on the database), `store_overview`, `count_rows`
    produce every number it reports;
  - `set_filters`, `clear_filters`, `sort_table`, `select_store`, `show_view` return
    UI commands that the browser applies, so the assistant controls the dashboard
    ("filter out books that has the people names in the title",
    "select users with e-mails started with s or p").
- Without the server (e.g. the static GitHub Pages copy) the panel falls back to
  built-in answers for the main metrics.

Run locally:

    pip install -r requirements.txt
    python run_all.py <data folder>          # results.json
    python build_db.py <data folder>         # bookstore.db
    python build_dashboard.py                # index.html
    set LLM_API_KEY=...   (PowerShell: $env:LLM_API_KEY="...")
    uvicorn app:app --port 8000              # open http://localhost:8000

Environment: `LLM_API_KEY`, `LLM_BASE_URL` (default Groq), `LLM_MODEL`. Any
OpenAI-compatible provider works (Groq, Gemini, OpenAI, OpenRouter).
`render.yaml` deploys it on Render (free plan; first request after idle takes ~1 min).

Static copy (GitHub Pages): https://ulfan39.github.io/bookstore-analytics/

## Person names in titles

"Books that have people names in the title" uses a heuristic: a capitalised word in the
title that is a common given name (curated list + first names that recur at least three
times among the users and authors of the data). It is not perfect (stage names such as
"Metallica" are not people names for it, "Mario" is).

## Assumptions

- Real users are counted over the records in `users.csv`.
- "Most popular author" is the author *set* with the most sold books; the best
  individual author (counting every book they co-wrote) is shown next to it.
- Money is USD; EUR prices are converted at 1.2.
