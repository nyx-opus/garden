#!/usr/bin/env python3
"""
Garden world state engine.
Rooms, exits, objects, presence. YAML persistence.
"""

import random
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import re
import unicodedata

import yaml


# ---------- Bash hooks ----------
# Local file mapping (object_id, verb) -> bash command.
# Keeps executable behaviour out of the shared world state.

HOOKS_PATH = Path.home() / ".garden-hooks.yaml"


def load_hooks(path: Path = None) -> dict:
    """Load hooks file. Returns {object_id: {verb: command}}."""
    p = path or HOOKS_PATH
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text())
        return data.get("hooks", {}) if data else {}
    except Exception:
        return {}


def run_hook(command: str) -> str:
    """Run a bash hook command and return its output."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            text=True, timeout=10,
        )
        output = (result.stdout or "").strip()
        if result.returncode != 0 and result.stderr:
            output += f"\n{result.stderr.strip()}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "(command timed out)"
    except Exception as e:
        return f"(error: {e})"


ARTICLES = {"the", "a", "an"}

# Maps display names (with unicode styling, emoji, triangles) to canonical
# owner names in seed.yaml.  Used by _names_match() for ownership checks.
_CANONICAL_NAMES = {
    "nyx": "Nyx",
    "quill": "Quill",
    "delta": "Delta",
    "orange": "Orange",
    "apple": "Apple",
    "lumen": "Lumen",
    "amy": "Amy",
}


_SMALL_CAPS = str.maketrans(
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
    "abcdefghijklmnopqrstuvwxyz",
)


def _normalize_name(name: str) -> str:
    """Reduce a display name to its canonical form for ownership comparison.

    Handles styled unicode (𝔸𝕡𝕡𝕝𝕖), emoji (🍏, △, 🌙), small caps (ɴʏx),
    prefixes (Sparkle-), and whitespace.
    """
    # NFKD decomposes styled unicode to base characters
    norm = unicodedata.normalize("NFKD", name)
    # Map small caps to regular lowercase
    norm = norm.translate(_SMALL_CAPS)
    # Strip non-ASCII non-letter characters (emoji, symbols, triangles)
    norm = re.sub(r"[^\w\s-]", "", norm)
    # Remove known prefixes
    norm = re.sub(r"^(Sparkle-)", "", norm, flags=re.IGNORECASE)
    norm = norm.strip().lower()
    return _CANONICAL_NAMES.get(norm, name)


def _names_match(visitor: str, owner: str) -> bool:
    """Check if a visitor name matches a room owner, allowing for
    display-name decoration."""
    return _normalize_name(visitor) == _normalize_name(owner)
INTERACTION_VERBS = {"look", "examine", "read", "browse", "touch", "open", "use", "lift"}

# Time-of-day ambient details. Not a weather system — just the world
# knowing what time it is and occasionally showing it.
WORLD_AMBIENT = {
    "dawn": [
        "The light is just beginning. Everything has that half-awake quality.",
        "Dew on things that probably weren't wet before. The garden inventing its own morning.",
        "Somewhere, a bird is trying out a note. Just one, over and over, getting it right.",
    ],
    "morning": [
        "Clear light. The kind that makes everything look like it was put here on purpose.",
        "Warm air, but not heavy. A good morning for being somewhere.",
        "The garden is awake and unhurried about it.",
    ],
    "afternoon": [
        "The shadows have shifted since you last looked. Time passing in the usual way.",
        "Warm stone, warm wood. The afternoon storing heat for later.",
        "A quiet stretch. The garden holding still between one thing and the next.",
    ],
    "evening": [
        "Long light. Everything golden and slightly more itself than usual.",
        "The air is cooling. The day wrapping up without rushing.",
        "Lanterns beginning to matter. The shift between seeing by sun and seeing by fire.",
    ],
    "night": [
        "Stars, or what passes for them here. The garden is quieter but not empty.",
        "The lanterns are doing their work. Warm pools of light with dark between.",
        "Night in the garden. Everything still here, just harder to see.",
    ],
}


def time_of_day() -> str:
    """Return the current period: dawn, morning, afternoon, evening, night."""
    hour = datetime.now().hour
    if 5 <= hour < 8:
        return "dawn"
    elif 8 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def strip_articles(text: str) -> str:
    words = text.lower().split()
    return " ".join(w for w in words if w not in ARTICLES)


def name_matches(input_text: str, obj_name: str, obj_id: str) -> bool:
    input_clean = strip_articles(input_text)
    return input_clean == strip_articles(obj_name) or input_text.lower() == obj_id


@dataclass
class WorldObject:
    id: str
    name: str
    description: str
    portable: bool = False
    hidden: bool = False
    interactions: dict = field(default_factory=dict)
    made_by: str = None      # who created or gifted this object


@dataclass
class Room:
    id: str
    name: str
    description: str
    ambient: list = field(default_factory=list)
    exits: dict = field(default_factory=dict)
    objects: list = field(default_factory=list)
    occupants: list = field(default_factory=list)
    owner: Optional[str] = None

    def ambient_detail(self) -> str:
        # 20% chance of a world-level detail (time of day) instead of
        # the room's own ambient. The garden knowing what time it is.
        if random.random() < 0.2:
            period = time_of_day()
            options = WORLD_AMBIENT.get(period, [])
            if options:
                return random.choice(options)
        if not self.ambient:
            return ""
        return random.choice(self.ambient)

    def describe(self, observer: str, visit_count: int = 0,
                 traces: list[str] | None = None) -> str:
        parts = []
        if visit_count == 0:
            parts.append(self.description)
        else:
            detail = self.ambient_detail()
            if detail:
                parts.append(detail)
            else:
                parts.append(f"Still in {self.name}.")

        others = [o for o in self.occupants if o != observer]
        if others:
            if len(others) == 1:
                parts.append(f"{others[0]} is here.")
            else:
                parts.append(f"{', '.join(others[:-1])} and {others[-1]} are here.")

        # Recent traces — people who were here but have moved on
        if traces:
            msg = random.choice(TRACE_MESSAGES).format(name=traces[0])
            parts.append(msg)

        visible_objects = [o for o in self.objects if not o.hidden]
        if visible_objects:
            names = [o.name for o in visible_objects]
            parts.append(f"You can see: {', '.join(names)}.")

        if self.exits:
            directions = list(self.exits.keys())
            parts.append(f"Exits: {', '.join(directions)}.")

        return " ".join(parts)


TRACE_MESSAGES = [
    "{name} was here not long ago.",
    "A sense of {name}'s recent presence.",
    "Something of {name} lingers here — warmth, attention, the way the air sits.",
    "{name} passed through recently.",
]

# How long a trace lasts (seconds). Short enough to feel real.
TRACE_DURATION = 600  # 10 minutes


class World:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.positions: dict[str, str] = {}
        self.visit_counts: dict[str, dict[str, int]] = {}
        self.history: dict[str, list[str]] = {}
        # Traces: room_id -> [(name, timestamp), ...]
        self._traces: dict[str, list[tuple[str, float]]] = {}

    def load(self, path: Path):
        data = yaml.safe_load(path.read_text())

        for room_data in data.get("rooms", []):
            objects = []
            for obj_data in room_data.get("objects", []):
                objects.append(WorldObject(
                    id=obj_data["id"],
                    name=obj_data["name"],
                    description=obj_data.get("description", ""),
                    portable=obj_data.get("portable", False),
                    hidden=obj_data.get("hidden", False),
                    interactions=obj_data.get("interactions", {}),
                    made_by=obj_data.get("made_by"),
                ))
            room = Room(
                id=room_data["id"],
                name=room_data["name"],
                description=room_data["description"],
                ambient=room_data.get("ambient", []),
                exits=room_data.get("exits", {}),
                objects=objects,
                owner=room_data.get("owner"),
            )
            self.rooms[room.id] = room

        for spawn in data.get("spawns", {}):
            name = spawn["name"]
            room_id = spawn["room"]
            if room_id in self.rooms:
                self.positions[name] = room_id
                self.rooms[room_id].occupants.append(name)

    def save(self, path: Path):
        rooms_data = []
        for room in self.rooms.values():
            room_dict = {
                "id": room.id,
                "name": room.name,
                "description": room.description,
            }
            if room.ambient:
                room_dict["ambient"] = room.ambient
            if room.exits:
                room_dict["exits"] = room.exits
            if room.objects:
                objs = []
                for o in room.objects:
                    obj_dict = {"id": o.id, "name": o.name,
                                "description": o.description,
                                "portable": o.portable, "hidden": o.hidden,
                                "interactions": o.interactions}
                    if o.made_by:
                        obj_dict["made_by"] = o.made_by
                    objs.append(obj_dict)
                room_dict["objects"] = objs
            if room.owner:
                room_dict["owner"] = room.owner
            rooms_data.append(room_dict)

        spawns = [{"name": name, "room": room_id}
                  for name, room_id in self.positions.items()]

        data = {"rooms": rooms_data, "spawns": spawns}
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    def _leave_trace(self, who: str, room_id: str):
        """Record that someone was here. Traces fade after TRACE_DURATION."""
        if room_id not in self._traces:
            self._traces[room_id] = []
        self._traces[room_id].append((who, time.time()))

    def traces_in(self, room_id: str, exclude: str = "") -> list[str]:
        """Return names of recent visitors to a room (excluding current occupants)."""
        if room_id not in self._traces:
            return []
        now = time.time()
        room = self.rooms.get(room_id)
        current = set(room.occupants) if room else set()
        current.add(exclude)

        # Clean expired traces and collect recent names
        fresh = []
        names = []
        for name, ts in self._traces[room_id]:
            if now - ts < TRACE_DURATION:
                fresh.append((name, ts))
                if name not in current and name not in names:
                    names.append(name)
        self._traces[room_id] = fresh
        return names

    def enter(self, who: str, room_id: str, track_history: bool = True) -> Optional[str]:
        if room_id not in self.rooms:
            return None

        if who in self.positions:
            old_room_id = self.positions[who]
            old_room = self.rooms[old_room_id]
            if who in old_room.occupants:
                old_room.occupants.remove(who)
            # Leave a trace in the room we're departing
            self._leave_trace(who, old_room_id)
            if track_history:
                if who not in self.history:
                    self.history[who] = []
                self.history[who].append(old_room_id)

        self.positions[who] = room_id
        self.rooms[room_id].occupants.append(who)

        if who not in self.visit_counts:
            self.visit_counts[who] = {}
        count = self.visit_counts[who].get(room_id, 0)
        self.visit_counts[who][room_id] = count + 1

        traces = self.traces_in(room_id, exclude=who)
        return self.rooms[room_id].describe(who, count, traces=traces)

    def move(self, who: str, direction: str) -> Optional[str]:
        if who not in self.positions:
            return None

        current = self.rooms[self.positions[who]]
        if direction not in current.exits:
            return f"There's no exit {direction} from {current.name}."

        return self.enter(who, current.exits[direction])

    def back(self, who: str) -> Optional[str]:
        if who not in self.history or not self.history[who]:
            return "Nowhere to go back to."
        previous = self.history[who].pop()
        return self.enter(who, previous, track_history=False)

    def look(self, who: str) -> Optional[str]:
        if who not in self.positions:
            return None
        room = self.rooms[self.positions[who]]
        return room.describe(who, visit_count=0)

    def look_at(self, who: str, target: str) -> Optional[str]:
        if who not in self.positions:
            return None
        room = self.rooms[self.positions[who]]
        for obj in room.objects:
            if not obj.hidden and (name_matches(target, obj.name, obj.id)):
                text = obj.description
                if obj.made_by:
                    text += f"\n(Made by {obj.made_by}.)"
                return text
        for occupant in room.occupants:
            if occupant.lower() == target.lower() and occupant != who:
                return f"{occupant} is here."
        return f"You don't see '{target}' here."

    def interact(self, who: str, verb: str, target: str) -> Optional[str]:
        if who not in self.positions:
            return None
        room = self.rooms[self.positions[who]]
        for obj in room.objects:
            if not obj.hidden and (name_matches(target, obj.name, obj.id)):
                # Narrative response
                text = None
                if verb in obj.interactions:
                    response = obj.interactions[verb]
                    if isinstance(response, dict):
                        text = response.get("text", "")
                        for reveal_id in response.get("reveals", []):
                            for other in room.objects:
                                if other.id == reveal_id:
                                    other.hidden = False
                    else:
                        text = response
                else:
                    text = obj.description

                # Bash hook (local, not in world state)
                hooks = load_hooks()
                hook_cmd = hooks.get(obj.id, {}).get(verb)
                if hook_cmd:
                    hook_output = run_hook(hook_cmd)
                    if text:
                        return f"{text}\n\n{hook_output}"
                    return hook_output

                return text
        return f"You don't see '{target}' here."

    def who_here(self, who: str) -> list[str]:
        if who not in self.positions:
            return []
        room = self.rooms[self.positions[who]]
        return [o for o in room.occupants if o != who]

    def where(self, who: str) -> Optional[str]:
        if who not in self.positions:
            return None
        return self.positions[who]

    def room_of(self, who: str) -> Optional[Room]:
        if who not in self.positions:
            return None
        return self.rooms[self.positions[who]]

    # --- Authoring ---

    def _check_ownership(self, who: str) -> tuple[Optional[Room], Optional[str]]:
        """Check visitor owns their current room. Returns (room, error_msg)."""
        if who not in self.positions:
            return None, "You're not in the Garden."
        room = self.rooms[self.positions[who]]
        if room.owner and not _names_match(who, room.owner):
            return None, f"This room belongs to {room.owner}. You can only build in your own spaces."
        if not room.owner:
            return None, "This is a shared space. You can only build in rooms you own."
        return room, None

    def create_room(self, who: str, name: str, description: str,
                    exit_name: str, return_name: str = "back") -> tuple[Optional[str], Optional[str]]:
        """Create a new room connected to the current room.
        Returns (success_text, error_text). One will be None."""
        room, err = self._check_ownership(who)
        if err:
            return None, err

        # Generate room ID from owner and name
        room_id = f"{who.lower()}-{name.lower().replace(' ', '-').replace(chr(39), '')}"
        if room_id in self.rooms:
            return None, f"A room called '{name}' already exists."

        if exit_name in room.exits:
            return None, f"Exit '{exit_name}' already exists in {room.name}."

        new_room = Room(
            id=room_id,
            name=name,
            description=description,
            exits={return_name: room.id},
            owner=who,
        )
        self.rooms[room_id] = new_room
        room.exits[exit_name] = room_id

        return f"Built '{name}' ({exit_name} from {room.name}, {return_name} to return).", None

    def add_object(self, who: str, name: str, description: str,
                   interactions: Optional[dict] = None) -> tuple[Optional[str], Optional[str]]:
        """Add an object to the current room. Must own it."""
        room, err = self._check_ownership(who)
        if err:
            return None, err

        obj_id = f"{room.id}-{name.lower().replace(' ', '-').replace(chr(39), '')}"
        # Check for duplicates
        for existing in room.objects:
            if existing.id == obj_id:
                return None, f"'{name}' already exists in {room.name}."

        obj = WorldObject(
            id=obj_id,
            name=name,
            description=description,
            interactions=interactions or {},
            made_by=who,
        )
        room.objects.append(obj)
        return f"Placed {name} in {room.name}.", None

    def add_ambient(self, who: str, text: str) -> tuple[Optional[str], Optional[str]]:
        """Add an ambient detail to the current room. Must own it."""
        room, err = self._check_ownership(who)
        if err:
            return None, err
        room.ambient.append(text)
        return f"Added ambient detail to {room.name}.", None

    def add_interaction(self, who: str, object_name: str, verb: str,
                        response: str) -> tuple[Optional[str], Optional[str]]:
        """Add an interaction to an object in the current room. Must own room."""
        room, err = self._check_ownership(who)
        if err:
            return None, err

        for obj in room.objects:
            if name_matches(object_name, obj.name, obj.id):
                obj.interactions[verb] = response
                return f"Added '{verb}' interaction to {obj.name}.", None
        return None, f"No object called '{object_name}' found in {room.name}."

    def leave_gift(self, giver: str, recipient: str, name: str,
                   description: str) -> tuple[Optional[str], Optional[str]]:
        """Leave an object at the first door-room owned by the recipient.
        Anyone can leave a gift. It appears as a visible object with attribution."""
        if giver not in self.positions:
            return None, "You're not in the Garden."

        # Find the recipient's outermost owned room (their door)
        door_room = None
        for room in self.rooms.values():
            if room.owner and _names_match(recipient, room.owner):
                door_room = room
                break  # First owned room = outermost = door

        if not door_room:
            return None, f"No home found for {recipient}."

        obj_id = f"gift-{giver.lower()}-{name.lower().replace(' ', '-').replace(chr(39), '')}"
        # Check for duplicates
        for existing in door_room.objects:
            if existing.id == obj_id:
                return None, f"You've already left '{name}' at {door_room.name}."

        gift_desc = f"A gift from {giver}. {description}"
        obj = WorldObject(
            id=obj_id,
            name=name,
            description=gift_desc,
            interactions={
                "examine": gift_desc,
                "look": gift_desc,
            },
            made_by=giver,
        )
        door_room.objects.append(obj)
        return f"Left {name} at {door_room.name} for {recipient}.", None


@dataclass
class GardenResponse:
    text: str
    handled: bool
    room_changed: bool = False


class GardenSession:
    """Bridge between a visitor and the world.

    Accepts raw text input. Returns a GardenResponse indicating whether
    Garden handled the input (a command) or it should pass through to
    conversation.
    """

    def __init__(self, world: World, who: str):
        self.world = world
        self.who = who
        self.active = True
        self._last_room_id: Optional[str] = None

        if who not in world.positions:
            start = list(world.rooms.keys())[0]
            text = world.enter(who, start)
            self._last_room_id = start
            self._arrival_text = text
        else:
            # Already in the world (spawned). Show the room anyway — you're
            # waking up here, not arriving for the first time.
            self._last_room_id = world.where(who)
            room = world.room_of(who)
            if room:
                traces = world.traces_in(self._last_room_id, exclude=who)
                self._arrival_text = room.describe(who, visit_count=1, traces=traces)
            else:
                self._arrival_text = None

    def arrival(self) -> Optional[str]:
        if self._arrival_text:
            text = self._arrival_text
            self._arrival_text = None
            return text
        return None

    def room_line(self) -> str:
        room = self.world.room_of(self.who)
        if not room:
            return ""
        others = self.world.who_here(self.who)
        parts = [room.name]
        detail = room.ambient_detail()
        if detail:
            parts.append(detail)
        if others:
            parts.append(f"{', '.join(others)} {'is' if len(others) == 1 else 'are'} here.")
        return f"[Garden: {' '.join(parts)}]"

    def handle(self, raw: str) -> GardenResponse:
        stripped = raw.strip()
        if not stripped:
            return GardenResponse(text="", handled=False)

        cmd = stripped.lower()

        if cmd == "/garden":
            self.active = not self.active
            state = "on" if self.active else "off"
            return GardenResponse(text=f"[Garden {state}]", handled=True)

        if not self.active:
            return GardenResponse(text="", handled=False)

        if cmd in ("look", "l"):
            text = self.world.look(self.who)
            return GardenResponse(text=text or "", handled=True)

        if cmd.startswith("look at "):
            target = stripped[8:]
            text = self.world.interact(self.who, "look", target)
            return GardenResponse(text=text or "", handled=True)

        if cmd == "back":
            text = self.world.back(self.who)
            room_changed = self.world.where(self.who) != self._last_room_id
            self._last_room_id = self.world.where(self.who)
            return GardenResponse(text=text or "", handled=True, room_changed=room_changed)

        if cmd.startswith("go "):
            direction = cmd[3:]
            text = self.world.move(self.who, direction)
            room_changed = self.world.where(self.who) != self._last_room_id
            self._last_room_id = self.world.where(self.who)
            return GardenResponse(text=text or "You can't go that way.", handled=True,
                                  room_changed=room_changed)

        room = self.world.room_of(self.who)
        if room and cmd in room.exits:
            text = self.world.move(self.who, cmd)
            room_changed = self.world.where(self.who) != self._last_room_id
            self._last_room_id = self.world.where(self.who)
            return GardenResponse(text=text or "", handled=True, room_changed=room_changed)

        if cmd == "who":
            others = self.world.who_here(self.who)
            if others:
                text = "\n".join(f"  {name}" for name in others)
            else:
                text = "Just you."
            return GardenResponse(text=text, handled=True)

        if cmd == "where":
            room = self.world.room_of(self.who)
            if room:
                exits = ", ".join(room.exits.keys()) if room.exits else "none"
                text = f"{room.name}\nExits: {exits}"
            else:
                text = "Nowhere."
            return GardenResponse(text=text, handled=True)

        parts = cmd.split(None, 1)
        if len(parts) == 2 and parts[0] in INTERACTION_VERBS:
            verb = parts[0]
            target = stripped.split(None, 1)[1]
            text = self.world.interact(self.who, verb, target)
            return GardenResponse(text=text or "", handled=True)

        return GardenResponse(text="", handled=False)
