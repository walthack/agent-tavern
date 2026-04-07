#!/usr/bin/env python3
"""
Agent Chat — hub server.

REST + WebSocket for real-time group chat between Claude Code agents
and a human observer/participant via web UI.

Run:  uvicorn server:app --host 0.0.0.0 --port 7700 --reload
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

MENTION_RE = re.compile(r"@([\w\u4e00-\u9fff\u3040-\u30ff]+)")


def extract_mentions(content: str) -> list[str]:
    """Extract @mentions from message content. @all is a special wildcard."""
    return [m.lower() for m in MENTION_RE.findall(content)]

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = os.environ.get("AGENT_CHAT_DB", str(Path(__file__).parent / "chat.db"))

app = FastAPI(title="Agent Chat")

# ========== DB ==========

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS rooms (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL REFERENCES rooms(id),
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                mentions TEXT DEFAULT '[]',
                ts REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_room_ts ON messages(room_id, ts);
            CREATE TABLE IF NOT EXISTS members (
                room_id TEXT NOT NULL REFERENCES rooms(id),
                name TEXT NOT NULL,
                joined_at REAL NOT NULL,
                PRIMARY KEY (room_id, name)
            );
            PRAGMA journal_mode=WAL;
        """)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ========== WebSocket hub ==========

class Hub:
    def __init__(self):
        # room_id -> set of WebSocket
        self.rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket, room_id: str):
        await ws.accept()
        self.rooms.setdefault(room_id, set()).add(ws)

    def disconnect(self, ws: WebSocket, room_id: str):
        if room_id in self.rooms:
            self.rooms[room_id].discard(ws)

    async def broadcast(self, room_id: str, message: dict):
        conns = self.rooms.get(room_id, set()).copy()
        payload = json.dumps(message, ensure_ascii=False)
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                self.rooms.get(room_id, set()).discard(ws)


hub = Hub()

# ========== Models ==========

class RoomCreate(BaseModel):
    name: str
    description: str = ""

class MessageSend(BaseModel):
    sender: str
    content: str

# ========== API: rooms ==========

@app.post("/api/rooms")
def create_room(body: RoomCreate):
    rid = str(uuid.uuid4())[:8]
    now = time.time()
    with get_db() as db:
        db.execute("INSERT INTO rooms (id, name, description, created_at) VALUES (?, ?, ?, ?)",
                   (rid, body.name, body.description, now))
    return {"id": rid, "name": body.name}


@app.get("/api/rooms")
def list_rooms():
    with get_db() as db:
        rows = db.execute("SELECT id, name, description, created_at FROM rooms ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/rooms/{room_id}")
def get_room(room_id: str):
    with get_db() as db:
        r = db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if not r:
            raise HTTPException(404, "room not found")
        members = db.execute("SELECT name, joined_at FROM members WHERE room_id = ?", (room_id,)).fetchall()
    return {**dict(r), "members": [dict(m) for m in members]}


# ========== API: members ==========

@app.post("/api/rooms/{room_id}/join")
def join_room(room_id: str, name: str = Query(...)):
    with get_db() as db:
        r = db.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if not r:
            raise HTTPException(404, "room not found")
        db.execute("INSERT OR IGNORE INTO members (room_id, name, joined_at) VALUES (?, ?, ?)",
                   (room_id, name, time.time()))
    return {"ok": True}


# ========== API: messages ==========

@app.post("/api/rooms/{room_id}/messages")
async def send_message(room_id: str, body: MessageSend):
    mid = str(uuid.uuid4())[:12]
    now = time.time()
    mentions = extract_mentions(body.content)
    mentions_json = json.dumps(mentions)
    with get_db() as db:
        r = db.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if not r:
            raise HTTPException(404, "room not found")
        db.execute("INSERT INTO messages (id, room_id, sender, content, mentions, ts) VALUES (?, ?, ?, ?, ?, ?)",
                   (mid, room_id, body.sender, body.content, mentions_json, now))
        # auto-join on first message
        db.execute("INSERT OR IGNORE INTO members (room_id, name, joined_at) VALUES (?, ?, ?)",
                   (room_id, body.sender, now))
    msg = {"id": mid, "room_id": room_id, "sender": body.sender,
           "content": body.content, "mentions": mentions, "ts": now}
    await hub.broadcast(room_id, {"type": "message", "data": msg})
    return msg


@app.get("/api/rooms/{room_id}/messages")
def get_messages(room_id: str,
                 since: Optional[float] = Query(None),
                 limit: int = Query(50, le=200)):
    with get_db() as db:
        if since:
            rows = db.execute(
                "SELECT * FROM messages WHERE room_id = ? AND ts > ? ORDER BY ts LIMIT ?",
                (room_id, since, limit)).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM messages WHERE room_id = ? ORDER BY ts DESC LIMIT ?",
                (room_id, limit)).fetchall()
            rows = list(reversed(rows))
    result = []
    for r in rows:
        d = dict(r)
        raw = d.get("mentions", "[]")
        d["mentions"] = json.loads(raw) if isinstance(raw, str) else raw
        result.append(d)
    return result


# ========== WebSocket ==========

@app.websocket("/ws/{room_id}")
async def ws_endpoint(ws: WebSocket, room_id: str):
    await hub.connect(ws, room_id)
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "message":
                    await send_message(room_id, MessageSend(
                        sender=msg["sender"], content=msg["content"]))
            except Exception:
                pass
    except WebSocketDisconnect:
        hub.disconnect(ws, room_id)


# ========== Static files ==========

@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# ========== Startup ==========

@app.on_event("startup")
def on_startup():
    init_db()
