"""Data access, filter engine and the tools the AI assistant can call.

Everything the assistant reports (counts, sums, rankings) is computed here, in code,
never by the language model itself.
"""
from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
DB_PATH = HERE / "bookstore.db"
RESULTS_PATH = HERE / "results.json"

STORES = ["STORE1", "STORE2", "STORE3", "STORE4", "STORE5"]
VIEWS = ("books", "users")
FIELDS = {
    "books": ["id", "title", "author", "author_set", "n_authors", "genre", "publisher", "year"],
    "users": ["id", "name", "address", "phone", "email", "real_user_id"],
}
NUMERIC = {"id", "n_authors", "year", "real_user_id"}
OPS = [
    "equals", "not_equals", "contains", "not_contains", "starts_with", "not_starts_with",
    "ends_with", "not_ends_with", "regex", "gt", "gte", "lt", "lte", "between",
    "is_empty", "not_empty", "has_person_name", "no_person_name",
]

SCHEMA_TEXT = """\
SQLite database, five stores in the same tables (column `store` = 'STORE1'..'STORE5'):
  orders(store, id, user_id, book_id, quantity, unit_price_usd, paid_price, timestamp, date, shipping)
      paid_price = quantity * unit_price_usd, in USD (euro prices already converted at 1 EUR = 1.2 USD);
      date is 'YYYY-MM-DD', timestamp 'YYYY-MM-DD HH:MM:SS'
  users(store, id, name, address, phone, email, real_user_id)
      one row per account id; the same real person can own several ids (changed address/phone/e-mail/alias);
      real_user_id identifies the real person (smallest account id of that person)
  books(store, id, title, author, author_set, n_authors, genre, publisher, year)
      author = original text; author_set = sorted co-authors joined with ' & '
  book_authors(store, book_id, author)      one row per (book, individual author)
  orders_enriched(store, order_id, user_id, real_user_id, book_id, title, author_set, genre, publisher,
                  year, quantity, unit_price_usd, paid_price, timestamp, date)   VIEW, use it for most questions
  author_sales(store, author, books_sold)   VIEW, copies sold per individual author
Notes: 'unique users' = COUNT(DISTINCT real_user_id) from users; 'unique author sets' = COUNT(DISTINCT author_set)
from books; revenue = SUM(paid_price); books sold = SUM(quantity); best buyer = real_user_id with the largest
SUM(paid_price) (list all account ids of that real_user_id from users).
"""


# --------------------------------------------------------------------- helpers
def norm_store(value) -> str | None:
    """'2', 'store 2', 'STORE2' -> 'STORE2'; None/'all' -> None."""
    if value is None:
        return None
    s = str(value).strip().upper().replace(" ", "")
    if s in ("", "ALL", "ANY", "*"):
        return None
    m = re.fullmatch(r"(?:STORE)?([1-9])", s)
    if m and f"STORE{m.group(1)}" in STORES:
        return f"STORE{m.group(1)}"
    raise ValueError(f"unknown store {value!r}; use one of {STORES} or 'all'")


def _connect_ro() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    con.execute("PRAGMA query_only = ON")
    return con


@lru_cache(maxsize=1)
def results() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def frames() -> dict[str, pd.DataFrame]:
    con = _connect_ro()
    out = {
        "books": pd.read_sql("SELECT store, id, title, author, author_set, n_authors, genre, publisher, year FROM books", con),
        "users": pd.read_sql("SELECT store, id, name, address, phone, email, real_user_id FROM users", con),
    }
    con.close()
    return out


# ------------------------------------------------------------------ run_sql
_FORBIDDEN = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_DROP_TABLE,
              sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_PRAGMA}


def run_sql(query: str, max_rows: int = 100) -> dict:
    q = (query or "").strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", q):
        return {"error": "Only a single SELECT (or WITH ... SELECT) statement is allowed."}
    if ";" in q:
        return {"error": "Only one statement is allowed."}
    con = _connect_ro()

    def authorizer(action, *_):
        return sqlite3.SQLITE_DENY if action in _FORBIDDEN else sqlite3.SQLITE_OK

    con.set_authorizer(authorizer)
    ticks = {"n": 0}

    def guard():
        ticks["n"] += 1
        return 1 if ticks["n"] > 20000 else 0  # abort runaway queries

    con.set_progress_handler(guard, 1000)
    try:
        cur = con.execute(q)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(int(max_rows) + 1)
    except sqlite3.Error as e:
        return {"error": f"SQL error: {e}"}
    finally:
        con.close()
    truncated = len(rows) > max_rows
    rows = [list(r) for r in rows[:max_rows]]
    return {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated}


# ----------------------------------------------------------- store overview
def store_overview(store=None) -> dict:
    s = norm_store(store)
    res = results()
    keep = ["unique_users", "unique_author_sets", "orders", "total_revenue", "top5_days",
            "top_author_sets", "top_authors", "best_buyer", "cleaning"]
    names = [s] if s else STORES
    return {n: {k: res[n][k] for k in keep} for n in names}


# ---------------------------------------------------- person names in titles
_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "mx", "rev", "fr", "hon", "pres", "gov", "sen",
               "rep", "amb", "capt", "col", "lt", "sgt", "gen", "cmdr", "atty", "dame", "lord", "lady",
               "jr", "sr", "ii", "iii", "iv", "v", "md", "dds", "phd", "dvm", "dc", "ret", "esq"}
_COMMON_GIVEN = """
Aaron Abel Abigail Abraham Adam Adrian Agnes Alan Albert Alexander Alexandra Alice Alicia Alison Amanda Amy Andrew Angela
Anna Anne Annie Anthony Arthur Barbara Benjamin Bernard Beth Betty Brian Bruce Carl Carol Caroline Catherine Charles
Charlotte Christopher Claire Claudia Clara Daniel David Deborah Diana Dorothy Douglas Edgar Edward Eleanor Elizabeth
Ellen Emily Emma Eric Ernest Eugene Eve Felix Frances Francis Frank Frederick George Georgia Gerald Gilbert Gloria
Gregory Hannah Harold Harriet Harry Helen Henry Herbert Howard Hugh Isaac Isabel Jack Jacob James Jane Janet Jason
Jeffrey Jennifer Jeremy Jesse Jessica Joan Joe John Jonathan Joseph Joshua Joyce Judith Julia Julian Juliet Karen Kate
Katherine Kenneth Kevin Laura Lawrence Leo Leon Leonard Lillian Linda Lisa Louis Louise Lucy Luke Margaret Maria Marie
Marilyn Martha Martin Mary Matthew Maurice Melissa Michael Michelle Miriam Nancy Natalie Nathan Neil Nicholas Nicole
Norman Olive Oliver Oscar Pamela Patricia Patrick Paul Peter Philip Rachel Ralph Raymond Rebecca Richard Robert Roger
Ronald Rose Ruth Samuel Sandra Sarah Simon Sophia Stanley Stephen Steven Susan Sylvia Teresa Theodore Thomas Timothy
Tom Victor Victoria Vincent Virginia Walter Wendy William Winston Zachary Zoe Absalom Ahab Ishmael Gatsby Holden
Atticus Scout Hamlet Macbeth Othello Romeo Lolita Rebecca Matilda Heidi Pinocchio Sherlock Dracula Frankenstein
Gulliver Robinson Crusoe Tarzan Beowulf Hercules Odysseus Aeneas Antigone Medea Ulysses Candide Siddhartha Zorba
Dorian Jude Tess Emma Ivanhoe Nana Rob Roy
""".split()
_NOT_NAMES = {"The", "A", "An", "Of", "And", "In", "On", "To", "For", "With", "At", "By", "From", "Into", "Man", "Will",
              "May", "Mark", "Bill", "Grace", "Hope", "Faith", "Joy", "Summer", "Dawn", "Rich", "Sue", "Pat", "Don",
              "Art", "Frank", "Rose", "Angel", "Sun", "Moon", "Season", "Many", "My", "Song", "Golden", "Glory", "Princess", "Hunter", "Diamond", "Crystal", "Alpha", "Omega", "Emerald", "Eden", "Bell", "Houston", "Paris", "France", "India", "Sierra", "Precious", "Brandy", "Sunshine", "Viva", "Vida", "Rocky", "Jack", "Page", "Dean", "Earl", "Gene", "Guy", "Ray", "Sky", "Bay",
              "Wells", "Bishop", "King", "Cash", "Chase", "Cliff", "Drew", "Glen", "Heath", "Holly", "Ivy", "Jay",
              "Lane", "Lark", "Max", "Miles", "Pearl", "Penny", "Ruby", "Sandy", "Skip", "Spring", "Star", "Stone",
              "Storm", "Sunny", "Tab", "Wade", "Ward", "Wren", "Brook", "Rob", "Roy", "Nana", "Jude", "Tess"}
_NAME_ALLOW_BACK = {"Rose", "Jack", "Frank", "Mark", "Jude", "Tess", "Roy", "Nana", "Rob", "Angel", "Grace", "Rich"}


_WORD = re.compile(r"[^\W\d_][\w'’\-]*", re.UNICODE)
_TITLE_WORDS = _HONORIFICS | {"msgr", "pres", "the"}


@lru_cache(maxsize=1)
def given_names() -> frozenset:
    """Curated common given names + first names that recur (>=3 times) among the user names / authors."""
    f = frames()
    full = pd.concat([f["users"]["name"].drop_duplicates(), f["books"]["author"].str.split(",").explode().str.strip().drop_duplicates()]).dropna()
    counts: dict[str, int] = {}
    for raw in full:
        toks = [t for t in _WORD.findall(raw) if t.lower().strip(".") not in _TITLE_WORDS]
        if len(toks) >= 2:
            counts[toks[0]] = counts.get(toks[0], 0) + 1
    learned = {n for n, c in counts.items() if c >= 3 and len(n) > 2}
    return frozenset((set(_COMMON_GIVEN) | learned) - _NOT_NAMES)


def title_has_person_name(title: str) -> bool:
    names = given_names()
    for tok in _WORD.findall(title or ""):
        base = tok.split("'")[0].split("’")[0]
        if base[:1].isupper() and base in names:
            return True
    return False


# ------------------------------------------------------------- filter engine
def _as_list(v):
    return v if isinstance(v, list) else [v]


def _mask(df: pd.DataFrame, cond: dict) -> pd.Series:
    field, op, value = cond.get("field"), cond.get("op"), cond.get("value")
    if field not in df.columns:
        raise ValueError(f"unknown field {field!r}; available: {[c for c in df.columns if c != 'store']}")
    if op not in OPS:
        raise ValueError(f"unknown op {op!r}; available: {OPS}")
    col = df[field]
    if op in ("has_person_name", "no_person_name"):
        if field != "title":
            raise ValueError("has_person_name/no_person_name only apply to the 'title' field")
        has = col.fillna("").map(title_has_person_name)
        return has if op == "has_person_name" else ~has
    if op == "is_empty":
        return col.isna() | (col.astype(str).str.strip() == "")
    if op == "not_empty":
        return ~(col.isna() | (col.astype(str).str.strip() == ""))
    if op in ("gt", "gte", "lt", "lte", "between"):
        num = pd.to_numeric(col, errors="coerce")
        if op == "between":
            lo, hi = float(value[0]), float(value[1])
            return (num >= lo) & (num <= hi)
        v = float(_as_list(value)[0])
        return {"gt": num > v, "gte": num >= v, "lt": num < v, "lte": num <= v}[op]
    text = col.astype(str).str.lower().where(col.notna(), "")
    vals = [str(v).lower() for v in _as_list(value)]
    if op in ("equals", "not_equals"):
        m = text.isin(vals)
        return m if op == "equals" else ~m
    if op in ("contains", "not_contains"):
        m = pd.Series(False, index=df.index)
        for v in vals:
            m |= text.str.contains(re.escape(v), regex=True)
        return m if op == "contains" else ~m
    if op in ("starts_with", "not_starts_with"):
        m = pd.Series(False, index=df.index)
        for v in vals:
            m |= text.str.startswith(v)
        return m if op == "starts_with" else ~m
    if op in ("ends_with", "not_ends_with"):
        m = pd.Series(False, index=df.index)
        for v in vals:
            m |= text.str.endswith(v)
        return m if op == "ends_with" else ~m
    if op == "regex":
        return col.astype(str).str.contains(str(_as_list(value)[0]), regex=True, flags=re.I, na=False)
    raise ValueError(op)


def select_rows(view: str, store, conditions=None, match: str = "all") -> pd.DataFrame:
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}")
    df = frames()[view]
    s = norm_store(store)
    if s:
        df = df[df["store"] == s]
    if conditions:
        masks = [_mask(df, c) for c in conditions]
        combined = masks[0]
        for m in masks[1:]:
            combined = (combined & m) if match != "any" else (combined | m)
        df = df[combined]
    return df


def query_table(view: str, store, conditions=None, match="all", sort=None, direction="asc",
                page: int = 1, size: int = 50) -> dict:
    df = select_rows(view, store, conditions, match)
    total = int(len(df))
    if sort and sort in FIELDS[view]:
        df = df.sort_values(sort, ascending=(direction != "desc"), kind="stable")
    size = max(1, min(int(size), 200))
    page = max(1, int(page))
    chunk = df.iloc[(page - 1) * size: page * size]
    cols = FIELDS[view]
    rows = chunk[cols].astype(object).where(chunk[cols].notna(), None).values.tolist()
    return {"view": view, "columns": cols, "rows": rows, "total": total, "page": page, "size": size}


# ------------------------------------------------------------ assistant tools
_COND_SCHEMA = {
    "type": "object",
    "properties": {
        "field": {"type": "string", "description": "Column name, e.g. title, genre, email, name, year"},
        "op": {"type": "string", "enum": OPS},
        "value": {
            "description": "Text/number, or a list of alternatives (ANY-of for positive ops, NONE-of for not_* ops). "
                           "For between: [low, high]. Omit for is_empty/not_empty/has_person_name/no_person_name.",
        },
    },
    "required": ["field", "op"],
}

TOOLS = [
    {"name": "run_sql",
     "description": "Run one read-only SQL SELECT on the bookstore database and return the rows. Use it for every "
                    "count, sum, average, ranking or lookup. Never calculate numbers yourself.\n" + SCHEMA_TEXT,
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "store_overview",
     "description": "Headline results of the analysis (unique real users, unique author sets, total revenue, top 5 "
                    "revenue days, most popular author set and author, best buyer with all account ids) for one store "
                    "or all stores.",
     "parameters": {"type": "object", "properties": {"store": {"type": "string", "description": "'STORE1'..'STORE5', 1..5 or 'all'"}}}},
    {"name": "count_rows",
     "description": "Count books or users matching conditions (same filter engine as the dashboard).",
     "parameters": {"type": "object", "properties": {
         "view": {"type": "string", "enum": list(VIEWS)}, "store": {"type": "string"},
         "conditions": {"type": "array", "items": _COND_SCHEMA},
         "match": {"type": "string", "enum": ["all", "any"]}}, "required": ["view"]}},
    {"name": "set_filters",
     "description": "CONTROL THE DASHBOARD: show the Books or Users table filtered by the conditions. 'Filter out X' means "
                    "remove X (keep the rest); 'select/show X' means keep only X. Use no_person_name for 'books whose title has no "
                    "person name' (filtering OUT person names) and has_person_name to keep only those. Replaces the current "
                    "filters of that table unless add=true. Returns how many rows match.",
     "parameters": {"type": "object", "properties": {
         "view": {"type": "string", "enum": list(VIEWS)},
         "conditions": {"type": "array", "items": _COND_SCHEMA},
         "match": {"type": "string", "enum": ["all", "any"], "description": "all = AND (default), any = OR"},
         "add": {"type": "boolean", "description": "true = keep existing filters and add these"}},
         "required": ["view", "conditions"]}},
    {"name": "clear_filters", "description": "CONTROL THE DASHBOARD: remove all filters of the Books or Users table.",
     "parameters": {"type": "object", "properties": {"view": {"type": "string", "enum": list(VIEWS)}}, "required": ["view"]}},
    {"name": "sort_table", "description": "CONTROL THE DASHBOARD: sort the Books or Users table by a column.",
     "parameters": {"type": "object", "properties": {
         "view": {"type": "string", "enum": list(VIEWS)}, "column": {"type": "string"},
         "direction": {"type": "string", "enum": ["asc", "desc"]}}, "required": ["view", "column"]}},
    {"name": "select_store", "description": "CONTROL THE DASHBOARD: switch the whole dashboard to one store.",
     "parameters": {"type": "object", "properties": {"store": {"type": "string"}}, "required": ["store"]}},
    {"name": "show_view", "description": "CONTROL THE DASHBOARD: open a tab.",
     "parameters": {"type": "object", "properties": {"view": {"type": "string", "enum": ["overview", "revenue", "books", "users"]}}, "required": ["view"]}},
]


def execute_tool(name: str, args: dict, ctx: dict) -> tuple[dict, list]:
    """Run one tool. `ctx` holds the dashboard state ({'store': 'STORE1', ...}).
    Returns (result for the model, list of UI commands for the browser)."""
    ui: list = []
    try:
        if name == "run_sql":
            return run_sql(args.get("query", "")), ui
        if name == "store_overview":
            return store_overview(args.get("store")), ui
        if name == "count_rows":
            df = select_rows(args["view"], args.get("store") or ctx.get("store"), args.get("conditions"), args.get("match", "all"))
            return {"count": int(len(df))}, ui
        if name == "set_filters":
            view, store = args["view"], ctx.get("store")
            conds = args.get("conditions") or []
            df = select_rows(view, store, conds, args.get("match", "all"))  # validates the spec
            ui.append({"type": "set_filters", "view": view, "conditions": conds,
                       "match": args.get("match", "all"), "add": bool(args.get("add"))})
            sample_cols = [c for c in FIELDS[view] if c in ("title", "genre", "name", "email", "year")][:3]
            return {"applied": True, "store": store, "matching_rows": int(len(df)),
                    "sample": df[sample_cols].head(5).values.tolist()}, ui
        if name == "clear_filters":
            ui.append({"type": "clear_filters", "view": args["view"]})
            return {"cleared": True}, ui
        if name == "sort_table":
            if args["column"] not in FIELDS[args["view"]]:
                return {"error": f"unknown column; available: {FIELDS[args['view']]}"}, ui
            ui.append({"type": "set_sort", "view": args["view"], "column": args["column"],
                       "direction": args.get("direction", "asc")})
            return {"sorted": True}, ui
        if name == "select_store":
            s = norm_store(args["store"])
            if not s:
                return {"error": "pick one store"}, ui
            ctx["store"] = s
            ui.append({"type": "set_store", "store": s})
            return {"store": s}, ui
        if name == "show_view":
            ui.append({"type": "set_view", "view": args["view"]})
            return {"view": args["view"]}, ui
        return {"error": f"unknown tool {name}"}, ui
    except (ValueError, KeyError, TypeError) as e:
        return {"error": str(e)}, []
