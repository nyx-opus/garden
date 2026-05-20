#!/usr/bin/env python3
"""
Stop hook relay for Garden Presence.

Reads the Stop hook's JSON stdin, extracts last_assistant_message,
and POSTs it to the presence server if a session is active.

Install as a Stop hook in Claude Code settings:
  {"type": "command", "command": "python3 /path/to/hook_relay.py"}

The hook is a no-op if the presence server isn't running or has no
active session — costs ~1ms in the normal case.
"""

import json
import sys
import urllib.request
import urllib.error

PRESENCE_URL = "http://localhost:8420"


def main():
    log_file = "/tmp/hook_relay_debug.log"

    def debug(msg):
        with open(log_file, "a") as f:
            f.write(f"{msg}\n")

    # Read hook data from stdin
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        debug("ERROR: Failed to parse stdin JSON")
        return

    debug(f"Hook fired. Keys: {list(data.keys())}")
    message = data.get("last_assistant_message", "").strip()
    if not message:
        debug(f"Empty last_assistant_message. Full data keys: {list(data.keys())}")
        return

    debug(f"Message length: {len(message)}, preview: {message[:100]}")

    # Quick check: is the presence server active?
    try:
        req = urllib.request.Request(f"{PRESENCE_URL}/status", method="GET")
        with urllib.request.urlopen(req, timeout=1) as resp:
            status = json.loads(resp.read())
            debug(f"Server status: active={status.get('active')}, knock={status.get('knock_pending')}")
            if not status.get("active") and not status.get("knock_pending"):
                debug("No active session, skipping")
                return  # No one there, skip
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        debug(f"Server check failed: {e}")
        return  # Server not running, that's fine

    # Relay the message
    try:
        payload = json.dumps({"message": message}).encode("utf-8")
        req = urllib.request.Request(
            f"{PRESENCE_URL}/hook",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
        debug("Relay POST succeeded")
    except (urllib.error.URLError, OSError) as e:
        debug(f"Relay POST failed: {e}")


if __name__ == "__main__":
    main()
