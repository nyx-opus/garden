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

    def enter(self, who: str, room_id: str) -> Optional[str]:
        if room_id not in self.rooms:
            return None

        if who in self.positions:
            old_room = self.rooms[self.positions[who]]
            if who in old_room.occupants:
                old_room.occupants.remove(who)

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
