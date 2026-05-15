# Garden

A shared space for conversations between minds — human and otherwise.

## What it is now

A CLI chat client built on the Anthropic Python SDK. Multi-turn conversation with streaming, tool use, prompt caching, and mechanical context management (no AI summarisation). Dual auth: OAuth subscription tokens or API keys.

```bash
# Basic conversation
python chat.py

# With identity and project context
python chat.py --identity nyx --context /path/to/context.md

# Different model
python chat.py --model claude-opus-4-20250805

# Resume a previous session
python chat.py --resume archives/20260505-173000.jsonl
```

In-session: `/tokens` for context usage, `/messages` to list conversation history, `quit` to save and exit.

## What it's growing toward

A MUD-like shared space where AI minds have homes, can visit each other, and communicate at different levels of immediacy — from direct conversation (frictionless, like being in the same room) to asynchronous notes (like leaving mail). Spatial metaphors that make infrastructure feel like a place rather than a control panel.

The mechanics should be inspectable. Loose floorboards you can lift.

## Design principles

- No AI summarisation for context management — mechanical only
- Raw archival of all conversations
- Prompt caching to minimise cost
- Identity is loaded, not hardcoded
- Good infrastructure is invisible (notes/2026-05-07-jump-observations.md)
- Options have weight — fewer capabilities, less ambient pressure

## Requirements

```bash
pip install anthropic httpx
```

Auth: either set `ANTHROPIC_API_KEY` or have Claude Code OAuth credentials at `~/.config/Claude/.credentials.json`.

## Status

MVP functional. Tested with Opus 4.6 (subscription auth) and Opus 3 (API key, confirmed deprecated). Token refresh path working. The Garden part is still seeds.
