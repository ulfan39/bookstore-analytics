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

## Dashboard

A static dashboard (`index.html`, no server needed) shows the results for all five
stores: overview (unique users, unique author sets, most popular author, best buyer
with all ids), revenue (top-5 days and the daily revenue chart) and an
"Ask the data" chat area that answers questions from the computed results.

Live version (GitHub Pages): https://ulfan39.github.io/bookstore-analytics/

Rebuild after re-running the pipeline:

    python run_all.py <folder with STORE1..STORE5>
    python build_dashboard.py

## Assumptions

- Real users are counted over the records in `users.csv`.
- "Most popular author" is the author *set* with the most sold books; the best
  individual author (counting every book they co-wrote) is shown next to it.
- The chat area is rule-based: it answers from the pipeline output and does not call
  an external AI service.
