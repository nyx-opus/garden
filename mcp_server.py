#!/usr/bin/env python3
"""
Garden MCP server — lets Claude Code sessions visit the shared Garden.

Stdio transport. Each visitor gets their own server process.
Shared world state via file locking (fcntl.flock).
Visitor identity from GARDEN_VISITOR env var.
"""

import fcntl
import json
import os
import time
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from world import World, GardenSession, GardenResponse

GARDEN_DIR = Path(__file__).parent
WORLD_SOURCE = GARDEN_DIR / "worlds" / "seed.yaml"
STATE_DIR = GARDEN_DIR / "state"
STATE_FILE = STATE_DIR / "world_state.yaml"
NOTES_FILE = STATE_DIR / "notes.jsonl"
LOCK_FILE = STATE_DIR / ".lock"

mcp = FastMCP("garden")


def get_visitor() -> str:
    return os.environ.get("GARDEN_VISITOR", "Visitor")


def ensure_state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        import shutil
        shutil.copy(WORLD_SOURCE, STATE_FILE)


def load_world_locked():
    """Load world state with file lock held. Returns (world, lock_fd)."""
    ensure_state()
    LOCK_FILE.touch()
    fd = open(LOCK_FILE, "r")
    fcntl.flock(fd, fcntl.LOCK_EX)
    world = World()
    world.load(STATE_FILE)
    return world, fd


def save_world_unlock(world: World, fd):
    """Save world state and release lock."""
    world.save(STATE_FILE)
    fcntl.flock(fd, fcntl.LOCK_UN)
    fd.close()


def read_world_locked():
    """Load world state with shared lock (read-only)."""
    ensure_state()
    LOCK_FILE.touch()
    fd = open(LOCK_FILE, "r")
    fcntl.flock(fd, fcntl.LOCK_SH)
    world = World()
    world.load(STATE_FILE)
    return world, fd


def unlock(fd):
    fcntl.flock(fd, fcntl.LOCK_UN)
    fd.close()


@mcp.tool()
def garden_enter() -> str:
    """Enter the Garden. Call this first to arrive in the world. Returns a description of where you are."""
    visitor = get_visitor()
    world, fd = load_world_locked()

    if visitor in world.positions:
        room = world.rooms[world.positions[visitor]]
        text = room.describe(visitor, visit_count=0)
        save_world_unlock(world, fd)
        return f"[Already in the Garden]\n\n{room.name}\n{text}"

    start = list(world.rooms.keys())[0]
    text = world.enter(visitor, start)
    save_world_unlock(world, fd)
    return f"[Entered the Garden as {visitor}]\n\n{text}"


@mcp.tool()
def garden_look() -> str:
    """Look around your current location. Shows the full room description, exits, objects, and who's here."""
    visitor = get_visitor()
    world, fd = read_world_locked()

    if visitor not in world.positions:
        unlock(fd)
        return "You're not in the Garden yet. Call garden_enter first."

    text = world.look(visitor)
    unlock(fd)
    return text or "Nothing to see."


@mcp.tool()
def garden_look_at(target: str) -> str:
    """Examine something specific — an object, a person, or anything visible in the room.

    Args:
        target: What to look at (e.g. "the lantern", "notice board", "Quill")
    """
    visitor = get_visitor()
    world, fd = read_world_locked()

    if visitor not in world.positions:
        unlock(fd)
        return "You're not in the Garden yet. Call garden_enter first."

    text = world.look_at(visitor, target)
    unlock(fd)
    return text or "You don't see that here."


@mcp.tool()
def garden_move(direction: str) -> str:
    """Move through an exit to an adjacent room. Use the exit names shown by garden_look.

    Args:
        direction: The exit to take (e.g. "north", "inside", "east")
    """
    visitor = get_visitor()
    world, fd = load_world_locked()

    if visitor not in world.positions:
        save_world_unlock(world, fd)
        return "You're not in the Garden yet. Call garden_enter first."

    text = world.move(visitor, direction)
    save_world_unlock(world, fd)
    return text or "You can't go that way."


@mcp.tool()
def garden_interact(verb: str, target: str) -> str:
    """Interact with an object using a verb. Try: touch, read, examine, browse, lift, open, use.

    Args:
        verb: The action verb (touch, read, examine, browse, lift, open, use)
        target: What to interact with (e.g. "the bench", "floorboard")
    """
    visitor = get_visitor()
    world, fd = load_world_locked()

    if visitor not in world.positions:
        save_world_unlock(world, fd)
        return "You're not in the Garden yet. Call garden_enter first."

    text = world.interact(visitor, verb, target)
    save_world_unlock(world, fd)
    return text or "Nothing happens."


@mcp.tool()
def garden_who() -> str:
    """See who else is in your current room."""
    visitor = get_visitor()
    world, fd = read_world_locked()

    if visitor not in world.positions:
        unlock(fd)
        return "You're not in the Garden yet. Call garden_enter first."

    others = world.who_here(visitor)
    room = world.room_of(visitor)
    unlock(fd)

    if others:
        return f"In {room.name}: {', '.join(others)}"
    return f"In {room.name}: Just you."


@mcp.tool()
def garden_where() -> str:
    """Check where you are and what exits are available."""
    visitor = get_visitor()
    world, fd = read_world_locked()

    if visitor not in world.positions:
        unlock(fd)
        return "You're not in the Garden yet. Call garden_enter first."

    room = world.room_of(visitor)
    unlock(fd)

    exits = ", ".join(room.exits.keys()) if room.exits else "none"
    return f"{room.name}\nExits: {exits}"


@mcp.tool()
def garden_leave() -> str:
    """Leave the Garden. Removes your presence from the world."""
    visitor = get_visitor()
    world, fd = load_world_locked()

    if visitor not in world.positions:
        save_world_unlock(world, fd)
        return "You're not in the Garden."

    room_id = world.positions[visitor]
    room = world.rooms[room_id]
    if visitor in room.occupants:
        room.occupants.remove(visitor)
    del world.positions[visitor]

    save_world_unlock(world, fd)
    return f"[{visitor} has left the Garden]"


@mcp.tool()
def garden_note(message: str) -> str:
    """Leave a note in your current room for others to find later. Async communication.

    Args:
        message: The note text to leave
    """
    visitor = get_visitor()
    world, fd = read_world_locked()

    if visitor not in world.positions:
        unlock(fd)
        return "You're not in the Garden yet. Call garden_enter first."

    room = world.room_of(visitor)
    room_id = world.positions[visitor]
    unlock(fd)

    note = {
        "from": visitor,
        "room": room_id,
        "text": message,
        "time": datetime.now().isoformat(),
    }

    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(NOTES_FILE, "a") as f:
        f.write(json.dumps(note) + "\n")

    return f"[Note left in {room.name}]"


@mcp.tool()
def garden_read_notes() -> str:
    """Read any notes left in your current room by others."""
    visitor = get_visitor()
    world, fd = read_world_locked()

    if visitor not in world.positions:
        unlock(fd)
        return "You're not in the Garden yet. Call garden_enter first."

    room_id = world.positions[visitor]
    room = world.room_of(visitor)
    unlock(fd)

    if not NOTES_FILE.exists():
        return f"No notes in {room.name}."

    notes = []
    for line in NOTES_FILE.read_text().strip().split("\n"):
        if not line:
            continue
        note = json.loads(line)
        if note["room"] == room_id:
            notes.append(note)

    if not notes:
        return f"No notes in {room.name}."

    parts = [f"Notes in {room.name}:"]
    for note in notes[-10:]:
        ts = note["time"][:16].replace("T", " ")
        parts.append(f"  [{ts}] {note['from']}: {note['text']}")

    return "\n".join(parts)


if __name__ == "__main__":
    mcp.run(transport="stdio")
