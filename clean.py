"""Loading and cleaning of one STORE folder (orders.parquet, users.csv, books.yaml)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

EUR_TO_USD = 1.2

MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"),
            ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
            ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
            ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}

# ---------------------------------------------------------------- prices
_PRICE_NUM = re.compile(r"(\d+)(?:[.,](\d+))?")


def parse_price(raw: str) -> tuple[float, str] | tuple[None, None]:
    """'$ 35', '30.0USD', 'EUR37.50', '$57¢50', '63€50¢' -> (amount, currency)."""
    if raw is None:
        return None, None
    s = str(raw).strip()
    up = s.upper()
    if "€" in s or "EUR" in up:
        cur = "EUR"
    elif "$" in s or "USD" in up:
        cur = "USD"
    else:
        return None, None
    if "¢" in s:
        # '$39¢00' (symbol first) or '63€50¢' (symbol between): dollars, cents
        nums = re.findall(r"\d+", s)
        if len(nums) != 2:
            return None, None
        amount = int(nums[0]) + int(nums[1]) / 100
    else:
        m = _PRICE_NUM.search(s)
        if not m:
            return None, None
        amount = float(f"{m.group(1)}.{m.group(2) or '0'}")
    return amount, cur


# ------------------------------------------------------------ timestamps
_TIME = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2})(?:\.\d+)?)?"
    r"(?:\s*(?P<ap>[AaPp])\.?\s*[Mm]\.?)?"
)


def parse_timestamp(raw: str) -> datetime | None:
    """Parse the ~130 mixed date/time layouts of the dumps (no timezone info)."""
    if raw is None:
        return None
    s = str(raw).strip()
    t = _TIME.search(s)
    if not t:
        return None
    hour, minute = int(t["h"]), int(t["m"])
    second = int(t["s"] or 0)
    if t["ap"]:
        ap = t["ap"].lower()
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ap == "p" else 0)
    rest = (s[: t.start()] + " " + s[t.end():]).strip(" ,;")

    year = month = day = None
    if m := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", rest):  # ISO
        year, month, day = map(int, m.groups())
    elif m := re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", rest):  # DD.MM.YYYY
        day, month, year = map(int, m.groups())
    elif m := re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", rest):  # MM/DD/YY
        month, day, year = map(int, m.groups())
        if year < 100:
            year += 2000
    elif m := re.search(r"(\d{1,2})-([A-Za-z]+)-(\d{4})", rest):  # DD-Mon-YYYY
        day, year = int(m.group(1)), int(m.group(3))
        month = MONTHS.get(m.group(2).lower())
    elif m := re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})\s+(\d{4})", rest):  # Fri Apr 10 2026
        month = MONTHS.get(m.group(1).lower())
        day, year = int(m.group(2)), int(m.group(3))
    if None in (year, month, day):
        return None
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


# ---------------------------------------------------------------- loading
def load_store(folder: str | Path) -> dict[str, pd.DataFrame]:
    folder = Path(folder)
    orders = pd.read_parquet(folder / "orders.parquet")
    users = pd.read_csv(folder / "users.csv", dtype=str, keep_default_na=False)
    with open(folder / "books.yaml", encoding="utf-8") as f:
        books = pd.DataFrame(yaml.safe_load(f))
    books.columns = [c.lstrip(":") for c in books.columns]
    return {"orders": orders, "users": users, "books": books}


def clean_orders(orders: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    report: dict = {"rows_in": len(orders)}
    o = orders.copy()

    parsed = o["unit_price"].map(parse_price)
    o["price_amount"] = parsed.map(lambda p: p[0])
    o["currency"] = parsed.map(lambda p: p[1])
    o["timestamp"] = o["timestamp"].map(parse_timestamp)
    o["timestamp"] = pd.to_datetime(o["timestamp"])

    o["shipping"] = o["shipping"].replace({"": None, "NULL": None, "null": None})

    bad = o["price_amount"].isna() | o["timestamp"].isna() | o["quantity"].isna()
    report["malformed_dropped"] = int(bad.sum())
    o = o[~bad].copy()

    o["quantity"] = o["quantity"].astype(int)
    o = o[(o["quantity"] > 0) & (o["price_amount"] > 0)]

    rate = o["currency"].map({"USD": 1.0, "EUR": EUR_TO_USD})
    o["unit_price_usd"] = (o["price_amount"] * rate).round(2)
    o["paid_price"] = (o["quantity"] * o["unit_price_usd"]).round(2)
    o["date"] = o["timestamp"].dt.date

    before = len(o)
    o = o.drop_duplicates(subset="id")
    o = o.drop_duplicates(
        subset=["user_id", "book_id", "quantity", "unit_price_usd", "timestamp"]
    )
    report["duplicates_dropped"] = before - len(o)
    report["rows_out"] = len(o)
    return o.reset_index(drop=True), report
