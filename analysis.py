"""Analytics for one cleaned STORE: revenue, real users, author sets, best buyer."""
from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

import pandas as pd

from clean import clean_orders, load_store

CORE_FIELDS = ("name", "address", "phone", "email")


# ---------------------------------------------------------------- users
def _norm_users(users: pd.DataFrame) -> pd.DataFrame:
    u = users.copy()
    u["id"] = u["id"].astype("int64")
    u["name"] = u["name"].str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
    u["address"] = u["address"].str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
    u["phone"] = u["phone"].str.replace(r"\D", "", regex=True)
    u["email"] = u["email"].str.strip().str.lower()
    # empty strings are "missing": two missing values never count as a match
    for col in CORE_FIELDS:
        u[col] = u[col].replace("", pd.NA)
    return u


def reconcile_users(users: pd.DataFrame) -> pd.DataFrame:
    """Assign a `real_user` label to every user row.

    A person may change exactly one of (name, address, phone, email), so two
    records of one person always agree on at least three of these four fields.
    Records are linked when any 3-field combination is identical and non-missing,
    and connected components (union-find) are the real users.
    """
    u = _norm_users(users).reset_index(drop=True)
    parent = list(range(len(u)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for combo in combinations(CORE_FIELDS, 3):
        sub = u.dropna(subset=list(combo))
        for _, idx in sub.groupby(list(combo)).groups.items():
            idx = list(idx)
            for other in idx[1:]:
                union(idx[0], other)

    out = users.copy().reset_index(drop=True)
    out["id"] = out["id"].astype("int64")
    out["real_user"] = [find(i) for i in range(len(u))]
    return out


# -------------------------------------------------------------- authors
def author_sets(books: pd.DataFrame) -> pd.DataFrame:
    b = books.copy()
    b["authors"] = b["author"].map(
        lambda s: frozenset(p.strip() for p in str(s).split(",") if p.strip())
    )
    return b


def run_store(folder: str | Path) -> dict:
    data = load_store(folder)
    orders, report = clean_orders(data["orders"])
    users = reconcile_users(data["users"])
    books = author_sets(data["books"])

    # 1. daily revenue
    daily = (
        orders.groupby("date")["paid_price"].sum().round(2).rename("revenue").reset_index()
    )
    top5 = daily.sort_values(["revenue", "date"], ascending=[False, True]).head(5)

    # 2. real users
    n_users = int(users["real_user"].nunique())

    # 3. author sets in the catalogue
    n_author_sets = int(books["authors"].nunique())

    # 4. most popular author set / author by sold books
    sold = orders.groupby("book_id")["quantity"].sum().rename("sold").reset_index()
    sold = sold.merge(books[["id", "authors", "author"]], left_on="book_id", right_on="id")
    by_set = (
        sold.groupby("authors")["sold"].sum().sort_values(ascending=False)
    )
    top_set_count = int(by_set.iloc[0])
    top_sets = [sorted(s) for s, c in by_set.items() if c == top_set_count]
    exploded = sold.explode("authors")
    by_author = exploded.groupby("authors")["sold"].sum().sort_values(ascending=False)
    top_author_count = int(by_author.iloc[0])
    top_authors = [a for a, c in by_author.items() if c == top_author_count]

    # 5. best buyer
    merged = orders.merge(users[["id", "real_user"]], left_on="user_id", right_on="id")
    spend = merged.groupby("real_user")["paid_price"].sum().sort_values(ascending=False)
    best = spend.index[0]
    best_ids = sorted(int(i) for i in users.loc[users["real_user"] == best, "id"])

    return {
        "cleaning": report,
        "daily": daily,
        "top5_days": [
            {"date": d.isoformat(), "revenue": float(r)}
            for d, r in zip(top5["date"], top5["revenue"])
        ],
        "unique_users": n_users,
        "unique_author_sets": n_author_sets,
        "top_author_sets": {"sold": top_set_count, "sets": top_sets},
        "top_authors": {"sold": top_author_count, "authors": top_authors},
        "best_buyer": {
            "total_spent": round(float(spend.iloc[0]), 2),
            "user_ids": best_ids,
            "ids_with_orders": sorted(
                int(i) for i in merged.loc[merged["real_user"] == best, "user_id"].unique()
            ),
        },
        "total_revenue": round(float(orders["paid_price"].sum()), 2),
        "orders": int(len(orders)),
    }
