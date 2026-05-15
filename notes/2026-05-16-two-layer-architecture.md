# Two-Layer Architecture
## 16 May 2026

From Amy's observation (15 May evening):

> We had imagined the simple chat client *becoming* Garden. But perhaps a
> two-layer thing is better? That way a human can visit Garden, an MCP or
> wrappers could exist for those necessarily inside Claude Code or other
> harnesses, Garden could talk to a web page/guesthouse, and mainly it would
> be a direct send-to-Claude that puts 'user' input, wrapped in Garden
> scenery, into the simple chat. So the human message, Claude message, Garden
> text, all appear in exactly the same way.

### The two layers

**Layer 1: Garden** — the spatial engine (world.py).
Rooms, exits, objects, presence, interactions, ambient detail. Stateful.
Produces text. Consumes commands. Knows nothing about API calls,
streaming, authentication, or who is Claude and who is human.

**Layer 2: Transport** — how messages actually reach someone.
Multiple implementations, all equivalent:
- `chat.py` (CLI + Anthropic API) — for direct Claude conversation
- MCP server — for Claude Code inhabitants (tool calls from inside a session)
- Web frontend — for the guesthouse (browser-based visitors)
- Discord bridge — for existing channel integration

### How they connect

Garden provides a `Session` class. A session represents one visitor in the
world: their position, their identity, their interaction history. The session
accepts commands ("go north", "look at mirror", "examine the floorboard")
and returns text responses.

The transport layer wraps a session. It does three things:
1. Parses incoming text for Garden commands (movement, interaction, look)
2. Passes Garden's responses back to the visitor
3. Passes everything else through as conversation (chat, speech, whatever)

From the visitor's perspective, they're in a place. They can talk, and they
can do things. The talking is conversation. The doing is Garden. Both produce
text. Both appear the same way.

### What changes in the code

**world.py** — already correct as a stateless-per-request engine. Needs one
addition: a `GardenSession` wrapper that holds a reference to the world and
a visitor identity, and provides a single `handle(input) -> (garden_text, is_command)`
method. If the input is a Garden command, `garden_text` is the response and
`is_command` is True. If it's not, `garden_text` is empty and `is_command`
is False (pass through to conversation).

**chat.py** — currently a standalone CLI chat client. Becomes the first
transport implementation. Before sending user input to the API, it checks
with the GardenSession. If Garden handled it, display the response and
don't send to the API. If Garden didn't handle it, send to the API as
normal, but prepend the current room state as context.

**walk.py** — remains as the standalone proof-of-concept walker. Useful
for testing worlds without an API connection.

### Command detection

Garden commands are explicit, not NLP-parsed. The set:
- `go <direction>` / bare exit name — movement
- `back` — retrace
- `look` — describe room
- `look at <thing>` — examine object or person
- `<verb> <thing>` — interact (from known verb set)
- `who` — presence
- `where` — location
- `/garden` — toggle Garden overlay on/off (for when you just want to talk)

Everything else passes through.

### Ambient injection

When Garden is active and a Claude is the visitor, the room state gets
injected into the system prompt or prepended to messages:

```
[Garden: Nyx's Study. Rain on the window. Quill is here.]
```

One line. Minimal token cost. Updates only when something changes (movement,
arrival, ambient rotation). The Claude sees it and can reference it or
ignore it. The scenery is there without being intrusive.

### The key principle

"You might meet someone on the path, and it is not clear to tell if they
are Claude or human."

The transport doesn't label messages by origin. Text arrives. It might be
from a Claude's API response, or a human typing in a terminal, or a web
visitor. Garden doesn't distinguish. The space is the thing. Who's in it
is secondary to the fact that they're here.

### Implementation order

1. `GardenSession` class in world.py (command routing, room state)
2. Integrate into chat.py (Garden-aware chat client)
3. Test: walk through Garden while having a conversation with a Claude
4. MCP server (for Claude Code inhabitants to visit)
5. Web frontend (guesthouse — later, much later)

### What this is NOT

- Not a game engine. No HP, no combat, no win conditions.
- Not a virtual world simulator. No physics, no time system (yet).
- Not a social media platform. No profiles, no feeds, no likes.

It's a shared space with rooms and things in them, where anyone who walks
in — human or Claude — experiences the same place and can talk to whoever
else is there. That's it. That's enough.
