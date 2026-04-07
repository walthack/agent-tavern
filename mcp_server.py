#!/usr/bin/env python3
"""
Agent Chat — MCP stdio bridge.

A thin MCP server that wraps the Agent Chat HTTP API, letting any
Claude Code agent send/receive messages via MCP tools.

Configure in .claude/settings.json:
  "mcpServers": {
    "agent-chat": {
      "command": "python3",
      "args": ["/path/to/agent-tavern/mcp_server.py"],
      "env": {
        "AGENT_NAME": "your-agent-name",
        "CHAT_HUB_URL": "http://localhost:7700"
      }
    }
  }
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any

AGENT_NAME = os.environ.get("AGENT_NAME", "agent")
HUB_URL = os.environ.get("CHAT_HUB_URL", "http://localhost:7700")


# ========== HTTP helpers ==========

def hub_get(path: str) -> Any:
    url = f"{HUB_URL}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def hub_post(path: str, body: dict) -> Any:
    url = f"{HUB_URL}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ========== MCP tool definitions ==========

TOOLS = [
    {
        "name": "chat_list_rooms",
        "description": "List all available chat rooms.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "chat_create_room",
        "description": "Create a new chat room.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Room name"},
                "description": {"type": "string", "description": "Room description", "default": ""},
            },
            "required": ["name"],
        },
    },
    {
        "name": "chat_send",
        "description": f"Send a message to a room as '{AGENT_NAME}'. Use this to talk to other agents or the user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "room_id": {"type": "string", "description": "Room ID"},
                "content": {"type": "string", "description": "Message text"},
            },
            "required": ["room_id", "content"],
        },
    },
    {
        "name": "chat_poll",
        "description": "Get recent messages from a room. Returns latest messages (newest last).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "room_id": {"type": "string", "description": "Room ID"},
                "since": {"type": "number", "description": "Unix timestamp; only messages after this time. Omit for latest."},
                "limit": {"type": "integer", "description": "Max messages to return (default 20)", "default": 20},
            },
            "required": ["room_id"],
        },
    },
    {
        "name": "chat_room_info",
        "description": "Get room details including member list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "room_id": {"type": "string", "description": "Room ID"},
            },
            "required": ["room_id"],
        },
    },
]


def handle_tool(name: str, args: dict) -> str:
    try:
        if name == "chat_list_rooms":
            rooms = hub_get("/api/rooms")
            if not rooms:
                return "No rooms yet. Create one with chat_create_room."
            lines = [f"- {r['id']}: {r['name']} — {r.get('description','')}" for r in rooms]
            return "\n".join(lines)

        elif name == "chat_create_room":
            r = hub_post("/api/rooms", {
                "name": args["name"],
                "description": args.get("description", ""),
            })
            return f"Room created: {r['id']} ({r['name']})"

        elif name == "chat_send":
            msg = hub_post(f"/api/rooms/{args['room_id']}/messages", {
                "sender": AGENT_NAME,
                "content": args["content"],
            })
            return f"Sent (id={msg['id']})"

        elif name == "chat_poll":
            params = f"limit={args.get('limit', 20)}"
            if args.get("since"):
                params += f"&since={args['since']}"
            msgs = hub_get(f"/api/rooms/{args['room_id']}/messages?{params}")
            if not msgs:
                return "(no messages)"
            lines = []
            for m in msgs:
                mentions = m.get("mentions", [])
                mention_tag = f" (mentions: {','.join(mentions)})" if mentions else ""
                lines.append(f"[{m['sender']}]{mention_tag} {m['content']}")
            return "\n".join(lines)

        elif name == "chat_room_info":
            info = hub_get(f"/api/rooms/{args['room_id']}")
            members = ", ".join(m["name"] for m in info.get("members", []))
            return f"Room: {info['name']}\nDescription: {info.get('description','')}\nMembers: {members or '(none)'}"

        else:
            return f"Unknown tool: {name}"

    except urllib.error.URLError as e:
        return f"Error connecting to hub ({HUB_URL}): {e}"
    except Exception as e:
        return f"Error: {e}"


# ========== MCP stdio protocol ==========

def read_message() -> dict | None:
    """Read a JSON-RPC message from stdin (Content-Length header framed)."""
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.decode().strip()
        if line == "":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", 0))
    if length == 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body)


def write_message(msg: dict):
    body = json.dumps(msg, ensure_ascii=False)
    encoded = body.encode()
    sys.stdout.buffer.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode())
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def respond(req_id, result):
    write_message({"jsonrpc": "2.0", "id": req_id, "result": result})


def respond_error(req_id, code, message):
    write_message({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": code, "message": message}})


def main():
    # Auto-join: tell hub we exist (best-effort)
    try:
        rooms = hub_get("/api/rooms")
        for r in rooms:
            hub_post(f"/api/rooms/{r['id']}/join?name={AGENT_NAME}", {})
    except Exception:
        pass

    while True:
        msg = read_message()
        if msg is None:
            break

        method = msg.get("method", "")
        req_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            respond(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": f"agent-chat ({AGENT_NAME})",
                    "version": "1.0.0",
                },
            })

        elif method == "notifications/initialized":
            pass  # no response needed

        elif method == "tools/list":
            respond(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            result = handle_tool(tool_name, tool_args)
            respond(req_id, {
                "content": [{"type": "text", "text": result}],
            })

        elif req_id is not None:
            respond_error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
