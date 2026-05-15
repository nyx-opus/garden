#!/usr/bin/env python3
"""
Walk through the Garden interactively.
Proof of concept for the spatial experience.
"""

import readline
import sys
from pathlib import Path

from world import World


HELP_TEXT = """
Commands:
  look              — describe the room
  look at <thing>   — examine something or someone
  go <direction>    — move (north, south, east, west, inside, outside, etc.)
  who               — who else is in this room
  where             — where am I
  rooms             — list all rooms in the world
  help              — this message
  quit              — exit
"""


def main():
    world_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("worlds/seed.yaml")
    who = sys.argv[2] if len(sys.argv) > 2 else "Nyx"

    if not world_path.exists():
        print(f"World file not found: {world_path}")
        sys.exit(1)

    world = World()
    world.load(world_path)

    if who not in world.positions:
        start = list(world.rooms.keys())[0]
        print(f"[{who} enters the Garden at {world.rooms[start].name}]")
        print()
        print(world.enter(who, start))
    else:
        room = world.room_of(who)
        print(f"[{who} is in {room.name}]")
        print()
        print(world.look(who))

    print()

    try:
        while True:
            try:
                raw = input("> ").strip()
            except EOFError:
                break

            if not raw:
                continue

            cmd = raw.lower()

            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                print(HELP_TEXT)
            elif cmd == "look":
                print(world.look(who))
            elif cmd.startswith("look at "):
                target = raw[8:]
                print(world.look_at(who, target))
            elif cmd.startswith("go "):
                direction = cmd[3:]
                result = world.move(who, direction)
                if result:
                    print(result)
                else:
                    print("You can't go that way.")
            elif cmd == "who":
                others = world.who_here(who)
                if others:
                    for name in others:
                        print(f"  {name}")
                else:
                    print("Just you.")
            elif cmd == "where":
                room = world.room_of(who)
                if room:
                    print(f"{room.name} ({room.id})")
            elif cmd == "rooms":
                for rid, room in world.rooms.items():
                    marker = " <-- you" if world.where(who) == rid else ""
                    occupants = f" [{', '.join(room.occupants)}]" if room.occupants else ""
                    print(f"  {room.name}{occupants}{marker}")
            elif world.where(who) and cmd in world.rooms[world.where(who)].exits:
                result = world.move(who, cmd)
                if result:
                    print(result)
            else:
                print(f"I don't understand '{raw}'. Type 'help' for commands.")

            print()

    except KeyboardInterrupt:
        print()

    print(f"[{who} leaves the Garden]")


if __name__ == "__main__":
    main()
