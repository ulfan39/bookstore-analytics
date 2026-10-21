"""Tool-calling loop for any OpenAI-compatible chat-completions API.

Env vars:  LLM_API_KEY, LLM_BASE_URL (default Groq), LLM_MODEL
  Groq    : https://api.groq.com/openai/v1                           llama-3.3-70b-versatile
  Gemini  : https://generativelanguage.googleapis.com/v1beta/openai  gemini-2.0-flash
  OpenAI  : https://api.openai.com/v1                                gpt-4o-mini
"""
from __future__ import annotations

import json
import os

import requests

from tools import SCHEMA_TEXT, TOOLS, execute_tool

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
MAX_STEPS = 6

SYSTEM = """You are the assistant of a bookstore analytics dashboard (5 stores, STORE1..STORE5).
RULES
- Never guess or compute numbers yourself. For any count, sum, ranking, date or lookup call run_sql
  (or store_overview). Report exactly what the tool returned; if a tool errors, fix the call and retry.
- When the user asks to change what the dashboard shows (filter, select, sort, switch store, open a tab), call the
  matching control tool (set_filters, clear_filters, sort_table, select_store, show_view). Then tell the user
  what you did and how many rows now match. The current store is given below; if the user does not name a
  store, use the current one.
- "filter out X" = remove X and keep the rest. "select / show only X" = keep only X.
  Books whose title contains a person's name: has_person_name; without: no_person_name (field = title).
  E-mails started with s or p: field=email, op=starts_with, value=["s","p"].
- Dates are 'YYYY-MM-DD'. Money is USD with 2 decimals. A real person can own several user ids (real_user_id).
- Answer briefly in the language of the user's question.
""" + "\n" + SCHEMA_TEXT


def available() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def _post(messages):
    r = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
        json={"model": MODEL, "messages": messages, "temperature": 0,
              "tools": [{"type": "function", "function": t} for t in TOOLS], "tool_choice": "auto"},
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"LLM API {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]


def chat(history: list[dict], state: dict, post=_post) -> dict:
    """history: [{role, content}, ...] ending with the user's message.
    state: dashboard state {'store': 'STORE1', 'view': ...}.
    Returns {'reply': str, 'ui_commands': [...], 'tool_calls': [...]}."""
    ctx = {"store": state.get("store") or "STORE1"}
    system = SYSTEM + f"\nCurrent dashboard state: store={ctx['store']}, tab={state.get('view', 'overview')}."
    messages = [{"role": "system", "content": system}] + history[-12:]
    ui_all: list = []
    trace: list = []
    for _ in range(MAX_STEPS):
        msg = post(messages)
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"reply": (msg.get("content") or "").strip(), "ui_commands": ui_all, "tool_calls": trace}
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result, ui = execute_tool(name, args, ctx)
            ui_all.extend(ui)
            trace.append({"tool": name, "args": args})
            text = json.dumps(result, default=str, ensure_ascii=False)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": text[:6000]})
    return {"reply": "I could not finish this request in a few steps; please rephrase it.",
            "ui_commands": ui_all, "tool_calls": trace}
