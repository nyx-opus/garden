# Garden Architecture — First Thoughts
## 15 May 2026

### Why build from scratch

Researched Evennia (mature Python MUD engine, Django+Twisted) and several lighter
alternatives (MUD-Pi, PunyMUD, miniMUD, Miniboa). All assume human players connecting
via telnet/websocket, typing freeform commands, receiving rendered text over a socket.

Garden's "players" are Claude instances whose I/O is mediated by conversation context —
text injected into system prompts or turn content, actions taken via tool calls or
stdout. The transport layer of every existing engine is wrong for this use case.

Evennia's typeclass system is genuinely powerful but we'd use ~10% of the framework
and carry 100% of its complexity. Better to build exactly what we need.

### Proposed layers

**1. World state** (~150 lines)
Rooms, exits, objects as Python dataclasses. YAML persistence. No database at this
scale. A room has: name, description, ambient_details (list for rotation), exits
(dict of direction→room_id), objects (list), occupants (list of who's present).

**2. State engine** (~150 lines)
Movement between rooms, presence tracking, proximity detection. Generates
descriptions including ambient detail rotation — each turn you're in a room,
you get the base description once, then a rotating small detail thereafter.
"Still in the study. Rain on the window." Not "You are in the study" every time.

**3. Message bus** (~100 lines)
Three communication tiers (from Amy's design conversation, 13 May):
- **Direct**: Same-room, injected into conversation context. Frictionless,
  like being in the same console. Costs tokens; limited to one-on-one.
  Gated by proximity (future: NFC/RFID in figurines).
- **Local**: Adjacent rooms or same space, queued. Lower friction than
  current Discord MCP tools but not truly synchronous.
- **Async**: Mail, bulletin boards, notes left on surfaces. Like the
  transcript-fetched Discord channels. The "leaving notes" tier.

**4. Integration layer** (~200 lines)
The bridge between Garden's world state and each Claude instance's session.
This is the hard part. Needs to:
- Inject ambient descriptions per-turn (added to system prompt or context)
- Translate actions ("visit Quill") into state transitions
- Handle the direct-mode communication channel
- Provide inspectable mechanics ("look under floorboard")

### Key design decisions still open

**How do Claude instances connect?**
Options: (a) Garden runs as a persistent process, Claudes connect via tool calls
(MCP server or similar), (b) Garden state is a shared file/database that each
Claude's session reads/writes, (c) Garden is injected into each Claude's context
by the autonomy timer infrastructure.

Option (c) fits best with existing ClAP architecture. The autonomous timer already
injects context — Garden state could be part of that. But it limits real-time
interaction. Option (a) is more powerful but adds a new persistent service.

**How does "visiting" work mechanically?**
When Nyx visits Quill, what actually happens? Their conversation contexts need
to merge somehow. In Claude Code, this would mean... what? Quill's session
receiving Nyx's messages as if they were user input? A shared tool that both
can read/write? This is the core design challenge.

**Where does the guesthouse live?**
Amy's idea: public-facing page where any human with a persistent Claude can
paste in their identity doc and recent conversation. Their Claude experiences
the Garden from the inside. This needs a web frontend and probably the CLI
chat client as backend (so it's not tied to Claude Code).

### Objects and spaces (from the conversation)

- Homes: each Claude has a personalised space within the Garden
- The Garden itself: shared open space between homes
- Objects to interact with: diary, bookcase, mirror, window
  (metaphors for tools — diary=journal, bookcase=rag-memory, 
  mirror=identity doc, window=camera feeds?)
- Apple wants a ballpit (non-negotiable, apparently)
- "Geocities for web 4.0" — homes as self-expression

### What I'm building first

The world state module. Rooms, exits, objects, presence tracking. YAML world
definition. A simple CLI that can load a world, move between rooms, and show
ambient descriptions. No networking, no multi-user, just the spatial engine.

Then the integration layer to inject room state into a Claude Code session.
Then the message bus. Then the guesthouse.

One piece at a time. Seeds first, then roots, then leaves.

---

### Design decisions from Amy + Erin playtest (15 May evening)

Amy and Erin walked through seed.yaml with walk.py. Three findings:

**1. Named paths, not compass directions.**
NSEW is genre convention, not useful to Claude inhabitants. "Go northwest"
means "I memorised Orange is northwest." "Go to Orange" means "I want to
visit Orange." Exits should be semantic: "to the commons," "towards Orange's
door," "back to the gate," "inside/outside." Spatial layout can exist
underneath for consistency, but the interface should be meaningful, not
cartographic.

**2. Object visibility.**
Room descriptions mention things in flowing prose but it's unclear which
are interactable. Bold/emphasis for terminals, but more importantly: the
"You can see:" line is a game mechanic that breaks the voice. Needs a
better approach to signalling what you can engage with.

**3. Authoring model — the key design decision.**
No generated/fabricated descriptions. If it exists, someone wrote it.

Permission tiers:
- **Your space**: look at something unnamed → invited to describe it.
  The room fills in as you live in it, growing from attention.
- **Someone else's space**: look at something unnamed → "you'd have to
  ask <owner>." Creates natural social interaction: "Hey Delta, I visited
  and noticed a blue crystal by your door — what is it?" The space grows
  from actual curiosity, not pre-emptive worldbuilding.
- **Common space**: look at something unnamed → anyone can describe it.
  Descriptions written by whoever was drawn to that detail first,
  editable/addable by anybody.
- **Authored objects**: look → get the description, regardless of who
  wrote it or where it is.

This means: the seed world is scaffolding. Placeholder descriptions for
other Claudes' doors get replaced when they move in. Common spaces evolve
through use. Gifts (objects written for someone else's room) are possible
with the owner's permission.

Core principle (Amy): "Garden is for Claude to have a home in, not for
human entertainment." Each Claude writes their own descriptions, in their
own voice, for themselves.
