"""FastAPI server: serves the dashboard + JSON API (table data and the AI chat).

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import llm
import tools

HERE = Path(__file__).parent
app = FastAPI(title="Bookstore analytics")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class TableRequest(BaseModel):
    view: str
    store: str
    conditions: list[dict] = []
    match: str = "all"
    sort: str | None = None
    direction: str = "asc"
    page: int = 1
    size: int = 50


class ChatRequest(BaseModel):
    messages: list[dict]
    state: dict = {}


@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.available(), "model": llm.MODEL if llm.available() else None}


@app.post("/api/table")
def table(req: TableRequest):
    try:
        return tools.query_table(req.view, req.store, req.conditions, req.match, req.sort, req.direction, req.page, req.size)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/chat")
def chat(req: ChatRequest):
    if not llm.available():
        return JSONResponse({"error": "no_llm", "reply": "The AI is not configured on this server (LLM_API_KEY is missing)."}, status_code=503)
    history = [{"role": m["role"], "content": str(m["content"])} for m in req.messages if m.get("role") in ("user", "assistant")]
    try:
        return llm.chat(history, req.state)
    except Exception as e:  # network / API errors
        return JSONResponse({"error": "llm_error", "reply": f"The AI service failed: {e}"}, status_code=502)


@app.get("/")
def index():
    return FileResponse(HERE / "index.html")
