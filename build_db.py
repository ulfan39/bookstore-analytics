"""Build bookstore.db (SQLite) with the cleaned data of every STORE folder.

Usage: python build_db.py <folder with STORE1..STORE5> [bookstore.db]
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from analysis import process_store

SCHEMA = """
DROP VIEW IF EXISTS orders_enriched;
DROP VIEW IF EXISTS author_sales;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS book_authors;

CREATE TABLE orders (
    store TEXT NOT NULL, id INTEGER NOT NULL, user_id INTEGER NOT NULL, book_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL, unit_price_usd REAL NOT NULL, paid_price REAL NOT NULL,
    timestamp TEXT NOT NULL, date TEXT NOT NULL, shipping TEXT,
    PRIMARY KEY (store, id)
);
CREATE TABLE users (
    store TEXT NOT NULL, id INTEGER NOT NULL, name TEXT, address TEXT, phone TEXT, email TEXT,
    real_user_id INTEGER NOT NULL,
    PRIMARY KEY (store, id)
);
CREATE TABLE books (
    store TEXT NOT NULL, id INTEGER NOT NULL, title TEXT, author TEXT, author_set TEXT,
    n_authors INTEGER, genre TEXT, publisher TEXT, year INTEGER,
    PRIMARY KEY (store, id)
);
CREATE TABLE book_authors (store TEXT NOT NULL, book_id INTEGER NOT NULL, author TEXT NOT NULL);

CREATE INDEX idx_orders_user ON orders (store, user_id);
CREATE INDEX idx_orders_book ON orders (store, book_id);
CREATE INDEX idx_orders_date ON orders (store, date);
CREATE INDEX idx_users_real ON users (store, real_user_id);
CREATE INDEX idx_book_authors ON book_authors (store, book_id);

-- every order with its real buyer and book attributes
CREATE VIEW orders_enriched AS
SELECT o.store, o.id AS order_id, o.user_id, u.real_user_id, o.book_id, b.title, b.author_set,
       b.genre, b.publisher, b.year, o.quantity, o.unit_price_usd, o.paid_price, o.timestamp, o.date
FROM orders o
JOIN users u ON u.store = o.store AND u.id = o.user_id
JOIN books b ON b.store = o.store AND b.id = o.book_id;

-- copies sold per individual author (a co-written book counts for each author)
CREATE VIEW author_sales AS
SELECT o.store, a.author, SUM(o.quantity) AS books_sold
FROM orders o JOIN book_authors a ON a.store = o.store AND a.book_id = o.book_id
GROUP BY o.store, a.author;
"""


def main(data_dir: str, db_path: str = "bookstore.db") -> None:
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    for folder in sorted(p for p in Path(data_dir).glob("STORE*") if p.is_dir()):
        store = folder.name
        orders, users, books, _ = process_store(folder)

        o = orders[["id", "user_id", "book_id", "quantity", "unit_price_usd", "paid_price",
                    "timestamp", "date", "shipping"]].copy()
        o["timestamp"] = o["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        o["date"] = o["date"].astype(str)
        o.insert(0, "store", store)
        o.to_sql("orders", con, if_exists="append", index=False)

        u = users[["id", "name", "address", "phone", "email", "real_user_id"]].copy()
        u.insert(0, "store", store)
        u["address"] = u["address"].replace("", None)
        u.to_sql("users", con, if_exists="append", index=False)

        b = books.copy()
        b["author_set"] = b["authors"].map(lambda s: " & ".join(sorted(s)))
        b["n_authors"] = b["authors"].map(len)
        b = b[["id", "title", "author", "author_set", "n_authors", "genre", "publisher", "year"]]
        b.insert(0, "store", store)
        b.to_sql("books", con, if_exists="append", index=False)

        ba = books[["id", "authors"]].explode("authors").rename(columns={"id": "book_id", "authors": "author"})
        ba.insert(0, "store", store)
        ba.to_sql("book_authors", con, if_exists="append", index=False)
        print(store, len(o), "orders", len(u), "users", len(b), "books")
    con.commit()
    con.execute("VACUUM")
    con.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data", sys.argv[2] if len(sys.argv) > 2 else "bookstore.db")
