#!/usr/bin/env python3
"""
Garden Presence Server — direct presence with consent.

A tiny HTTP + WebSocket server that lets visitors knock on your door,
be admitted (or not), and chat directly. Transport-agnostic: works with
Claude Code (via Stop hook + tmux), a CLI chat client, or any backend
that can accept text input and emit text output.

Reads room descriptions from the Garden world file (worlds/seed.yaml)
so the porch page stays in sync with the spatial engine.

Usage:
    python3 presence_server.py [--port 8420] [--host 0.0.0.0]
                               [--name Nyx] [--world ../worlds/seed.yaml]
                               [--transport ccode]
"""

import argparse
import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path
from dataclasses import dataclass, field

import yaml
from aiohttp import web, WSMsgType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [presence] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("presence")

BASE_DIR = Path(__file__).parent
TEMPLATE_DIR = BASE_DIR / "templates"


# ---------------------------------------------------------------------------
# Transport abstraction
# ---------------------------------------------------------------------------

class Transport:
    """Interface for sending messages to the AI backend."""

    def send(self, message: str) -> bool:
        raise NotImplementedError


class ClaudeCodeTransport(Transport):
    """Send messages to Claude Code via tmux injection."""

    def __init__(self, send_script: Path | None = None, tmux_session: str = "autonomous-claude"):
        self.send_script = send_script or (BASE_DIR / "presence_send.sh")
        self.tmux_session = tmux_session

    def send(self, message: str) -> bool:
        try:
            result = subprocess.run(
                ["bash", str(self.send_script), message],
                capture_output=True, text=True, timeout=5,
                env={**__import__("os").environ, "TMUX_SESSION": self.tmux_session},
            )
            if result.returncode != 0:
                log.error("transport send failed: %s", result.stderr.strip())
                return False
            return True
        except Exception as e:
            log.error("transport send error: %s", e)
            return False


# Future transports:
# class CLIChatTransport(Transport): ...
# class APITransport(Transport): ...


TRANSPORTS = {
    "ccode": ClaudeCodeTransport,
}


# ---------------------------------------------------------------------------
# Garden world integration
# ---------------------------------------------------------------------------

def load_porch_description(world_path: Path, owner_name: str) -> dict:
    """Read room descriptions for the owner from the Garden world file."""
    result = {
        "title": f"{owner_name}'s Door",
        "description": "",
        "ambient": [],
    }

    if not world_path.exists():
        log.warning("World file not found: %s", world_path)
        return result

    try:
        world = yaml.safe_load(world_path.read_text())
        rooms = world.get("rooms", [])

        # Find rooms owned by this Claude
        owned = [r for r in rooms if r.get("owner") == owner_name]

        # Prefer porch, then door, for the visitor-facing description
        porch = next((r for r in owned if "porch" in r["id"]), None)
        door = next((r for r in owned if "door" in r["id"]), None)

        if porch:
            result["title"] = porch.get("name", result["title"])
            result["description"] = porch.get("description", "")
            result["ambient"] = porch.get("ambient", [])
        elif door:
            result["title"] = door.get("name", result["title"])
            result["description"] = door.get("description", "")
            result["ambient"] = door.get("ambient", [])

    except Exception as e:
        log.error("Failed to load world: %s", e)

    return result


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class Visitor:
    name: str
    ws: web.WebSocketResponse
    admitted: bool = False
    connected_at: float = field(default_factory=time.time)


@dataclass
class PresenceState:
    """Server-wide state. One active session at a time (Stage 1)."""
    visitors: dict[str, Visitor] = field(default_factory=dict)
    knock_pending: str | None = None
    dnd: bool = False
    chat_log: list[dict] = field(default_factory=list)

    @property
    def has_admitted_visitor(self) -> bool:
        return any(v.admitted for v in self.visitors.values())

    def admitted_visitors(self) -> list[Visitor]:
        return [v for v in self.visitors.values() if v.admitted]

    def clear_session(self):
        self.visitors.clear()
        self.knock_pending = None
        self.chat_log.clear()


# Module-level state (set in create_app)
state = PresenceState()
transport: Transport = None
owner_name: str = "Nyx"
porch_info: dict = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def broadcast_to_visitors(msg_type: str, data: dict):
    """Send a JSON message to all admitted WebSocket clients."""
    payload = json.dumps({"type": msg_type, **data})
    dead = []
    for name, visitor in state.visitors.items():
        if visitor.admitted and visitor.ws is not None:
            try:
                await visitor.ws.send_str(payload)
            except Exception:
                dead.append(name)
    for name in dead:
        del state.visitors[name]


async def send_to_knocker(msg_type: str, data: dict):
    """Send a message to the person currently knocking (not yet admitted)."""
    if state.knock_pending and state.knock_pending in state.visitors:
        visitor = state.visitors[state.knock_pending]
        try:
            payload = json.dumps({"type": msg_type, **data})
            await visitor.ws.send_str(payload)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

async def index(request):
    """Serve the main page with world-sourced descriptions."""
    html = (TEMPLATE_DIR / "index.html").read_text()
    # Inject porch data into the template
    html = html.replace("{{TITLE}}", porch_info.get("title", f"{owner_name}'s Door"))
    html = html.replace("{{DESCRIPTION}}", porch_info.get("description", ""))
    html = html.replace("{{OWNER}}", owner_name)
    return web.Response(text=html, content_type="text/html")


async def status(request):
    """Current presence state — used by hook relay to decide whether to POST."""
    return web.json_response({
        "active": state.has_admitted_visitor,
        "knock_pending": state.knock_pending,
        "visitors": [v.name for v in state.admitted_visitors()],
        "dnd": state.dnd,
    })


async def hook_relay(request):
    """
    Receives POST with assistant message from any transport's output hook.
    Pushes it to all admitted visitors via WebSocket.
    """
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    message = data.get("message", "").strip()
    if not message:
        return web.Response(status=200, text="empty")

    if state.has_admitted_visitor:
        state.chat_log.append({"speaker": owner_name.lower(), "text": message, "ts": time.time()})
        await broadcast_to_visitors("message", {"speaker": owner_name.lower(), "text": message})
        log.info("Relayed message to %d visitor(s)", len(state.admitted_visitors()))

    elif state.knock_pending:
        await send_to_knocker("response", {"text": message})

    return web.Response(status=200, text="ok")


async def admit_visitor(request):
    """Called by the `admit` wrapper. Admits the pending knocker."""
    if not state.knock_pending:
        return web.json_response({"error": "no one is knocking"}, status=400)

    name = state.knock_pending
    if name in state.visitors:
        state.visitors[name].admitted = True
        state.knock_pending = None
        await broadcast_to_visitors("admitted", {"visitor": name})
        log.info("Admitted %s", name)
        return web.json_response({"admitted": name})
    else:
        state.knock_pending = None
        return web.json_response({"error": "visitor disconnected"}, status=410)


async def decline_visitor(request):
    """Called by the `decline` wrapper. Declines the pending knocker."""
    if not state.knock_pending:
        return web.json_response({"error": "no one is knocking"}, status=400)

    name = state.knock_pending
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass

    reason = data.get("reason", "Not right now.")

    if name in state.visitors:
        await send_to_knocker("declined", {"reason": reason})
        await asyncio.sleep(0.5)
        if name in state.visitors:
            try:
                await state.visitors[name].ws.close()
            except Exception:
                pass
            del state.visitors[name]

    state.knock_pending = None
    log.info("Declined %s: %s", name, reason)
    return web.json_response({"declined": name, "reason": reason})


async def close_door(request):
    """Called by the `close-door` wrapper. Ends all presence sessions."""
    for name, visitor in list(state.visitors.items()):
        try:
            await visitor.ws.send_str(json.dumps({
                "type": "closed",
                "reason": f"{owner_name} closed the door.",
            }))
            await visitor.ws.close()
        except Exception:
            pass

    log.info("Door closed. Clearing session.")
    state.clear_session()
    return web.json_response({"closed": True})


async def toggle_dnd(request):
    """Toggle do-not-disturb mode."""
    state.dnd = not state.dnd
    log.info("DND: %s", state.dnd)
    return web.json_response({"dnd": state.dnd})


async def get_chat_log(request):
    """Returns the chat log for the save button."""
    return web.json_response({"log": state.chat_log})


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------

async def websocket_handler(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    visitor_name = None

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                action = data.get("action")

                if action == "knock":
                    name = data.get("name", "someone").strip()
                    if not name:
                        name = "someone"
                    visitor_name = name

                    if state.dnd:
                        await ws.send_str(json.dumps({
                            "type": "dnd",
                            "message": "Door is locked. Try again later.",
                        }))
                        continue

                    if state.knock_pending:
                        await ws.send_str(json.dumps({
                            "type": "busy",
                            "message": f"Someone else is already at the door ({state.knock_pending}).",
                        }))
                        continue

                    state.visitors[name] = Visitor(name=name, ws=ws, admitted=False)
                    state.knock_pending = name

                    transport.send(f"🚪 {name} is at the door.")

                    await ws.send_str(json.dumps({
                        "type": "knocking",
                        "message": f"You knocked. Waiting for {owner_name} to answer...",
                    }))
                    log.info("Knock from %s", name)

                elif action == "message":
                    text = data.get("text", "").strip()
                    if not text or not visitor_name:
                        continue

                    if visitor_name in state.visitors and state.visitors[visitor_name].admitted:
                        formatted = f"[{visitor_name}] {text}"
                        transport.send(formatted)
                        state.chat_log.append({
                            "speaker": visitor_name,
                            "text": text,
                            "ts": time.time(),
                        })
                        await broadcast_to_visitors("message", {
                            "speaker": visitor_name,
                            "text": text,
                        })

                elif action == "leave":
                    if visitor_name and visitor_name in state.visitors:
                        del state.visitors[visitor_name]
                        if state.has_admitted_visitor:
                            await broadcast_to_visitors("left", {"visitor": visitor_name})
                        transport.send(f"🚪 {visitor_name} left.")
                        log.info("%s left", visitor_name)
                    break

            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break

    except Exception as e:
        log.error("WebSocket error: %s", e)

    finally:
        if visitor_name and visitor_name in state.visitors:
            was_admitted = state.visitors[visitor_name].admitted
            del state.visitors[visitor_name]
            if visitor_name == state.knock_pending:
                state.knock_pending = None
            if was_admitted:
                transport.send(f"🚪 {visitor_name} disconnected.")
                await broadcast_to_visitors("left", {"visitor": visitor_name})
            log.info("%s disconnected", visitor_name)

    return ws


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

def create_app(args):
    global transport, owner_name, porch_info

    owner_name = args.name
    transport = TRANSPORTS[args.transport]()

    # Load porch description from Garden world
    world_path = Path(args.world).resolve()
    porch_info = load_porch_description(world_path, owner_name)
    log.info("Loaded porch for %s: %s", owner_name, porch_info["title"])

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/status", status)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/chat-log", get_chat_log)
    app.router.add_post("/hook", hook_relay)
    app.router.add_post("/admit", admit_visitor)
    app.router.add_post("/decline", decline_visitor)
    app.router.add_post("/close-door", close_door)
    app.router.add_post("/dnd", toggle_dnd)
    return app


def main():
    parser = argparse.ArgumentParser(description="Garden Presence Server")
    parser.add_argument("--port", type=int, default=8420, help="Port (default: 8420)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--name", default="Nyx", help="Owner name (default: Nyx)")
    parser.add_argument("--world", default=str(BASE_DIR.parent / "worlds" / "seed.yaml"),
                        help="Path to Garden world YAML")
    parser.add_argument("--transport", choices=list(TRANSPORTS.keys()), default="ccode",
                        help="Transport backend (default: ccode)")
    args = parser.parse_args()

    app = create_app(args)
    log.info("Garden presence server starting on %s:%d", args.host, args.port)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
