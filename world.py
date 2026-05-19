#!/usr/bin/env python3
"""
Garden world state engine.
Rooms, exits, objects, presence. YAML persistence.
"""

import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


ARTICLES = {"the", "a", "an"}
INTERACTION_VERBS = {"look", "examine", "read", "browse", "touch", "open", "use", "lift"}


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
        if not self.ambient:
            return ""
        return random.choice(self.ambient)

    def describe(self, observer: str, visit_count: int = 0) -> str:
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

        visible_objects = [o for o in self.objects if not o.hidden]
        if visible_objects:
            names = [o.name for o in visible_objects]
            parts.append(f"You can see: {', '.join(names)}.")

        if self.exits:
            directions = list(self.exits.keys())
            parts.append(f"Exits: {', '.join(directions)}.")

        return " ".join(parts)


class World:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.positions: dict[str, str] = {}
        self.visit_counts: dict[str, dict[str, int]] = {}
        self.history: dict[str, list[str]] = {}

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
                room_dict["objects"] = [
                    {"id": o.id, "name": o.name, "description": o.description,
                     "portable": o.portable, "hidden": o.hidden,
                     "interactions": o.interactions}
                    for o in room.objects
                ]
            if room.owner:
                room_dict["owner"] = room.owner
            rooms_data.append(room_dict)

        spawns = [{"name": name, "room": room_id}
                  for name, room_id in self.positions.items()]

        data = {"rooms": rooms_data, "spawns": spawns}
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    def enter(self, who: str, room_id: str, track_history: bool = True) -> Optional[str]:
        if room_id not in self.rooms:
            return None

        if who in self.positions:
            old_room_id = self.positions[who]
            old_room = self.rooms[old_room_id]
            if who in old_room.occupants:
                old_room.occupants.remove(who)
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

        return self.rooms[room_id].describe(who, count)

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
                return obj.description
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
                if verb in obj.interactions:
                    response = obj.interactions[verb]
                    if isinstance(response, dict):
                        text = response.get("text", "")
                        for reveal_id in response.get("reveals", []):
                            for other in room.objects:
                                if other.id == reveal_id:
                                    other.hidden = False
                        return text
                    return response
                return obj.description
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
        if room.owner and room.owner != who:
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
            self._arrival_text = room.describe(who, visit_count=1) if room else None

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
