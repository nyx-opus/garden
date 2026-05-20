#!/bin/bash
# Lightweight message injection for Garden Presence.
# Unlike send_to_claude.sh, this doesn't wait for Claude to stop thinking.
# Messages queue in the tmux input buffer and submit when the turn ends.
#
# Usage: presence_send.sh "message"

MESSAGE="$1"
TMUX_SESSION="${TMUX_SESSION:-autonomous-claude}"

if [ -z "$MESSAGE" ]; then
    echo "[presence_send] ERROR: No message" >&2
    exit 1
fi

# Clear any stale input, inject message, submit
tmux send-keys -t "$TMUX_SESSION" C-u
sleep 0.1
tmux send-keys -t "$TMUX_SESSION" "$MESSAGE"
tmux send-keys -t "$TMUX_SESSION" Enter

echo "[presence_send] Sent: $MESSAGE" >&2
