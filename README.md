# claude-hindsight-snapshots

Every 15 minutes of an active Claude Code session, a Haiku subagent summarizes what happened
(goal, changes, current state, durable facts) and saves it to a [Hindsight](https://github.com/vectorize-io/hindsight) memory bank.

## How it works

Claude Code has no timer hook, so `UserPromptSubmit`, `PostToolUse` and `Stop` hooks each do a
cheap timestamp check. When 15 minutes have passed, a detached worker:

1. reads only the transcript lines added since the last snapshot,
2. pipes them to `claude -p --model haiku` (no tools, not persisted),
3. POSTs the summary to Hindsight's `/v1/default/banks/<bank>/memories` (async retain).

Idle sessions produce nothing. Slices under 500 chars, or ones Haiku judges empty, are skipped.
Snapshots are tagged `claude-code`, `snapshot`, `host:<hostname>`, `project:<dir>`.

## Install

Requires `python3`, the `claude` CLI, and a reachable Hindsight REST API.

```bash
git clone https://github.com/<you>/claude-hindsight-snapshots
cd claude-hindsight-snapshots
HINDSIGHT_URL=http://127.0.0.1:8888 HINDSIGHT_BANK=brain ./install.sh
```

The installer copies the hook to `~/.claude/hooks/` and merges the hooks and env into
`~/.claude/settings.json` (idempotent; existing settings are kept).

## Configuration (env vars)

| Var | Default | |
|---|---|---|
| `HINDSIGHT_URL` | `http://127.0.0.1:8888` | Hindsight REST base URL |
| `HINDSIGHT_BANK` | `brain` | Memory bank |
| `HS_SNAPSHOT_INTERVAL` | `900` | Seconds between snapshots |
| `HS_SNAPSHOT_MODEL` | `haiku` | Summarizer model |
| `CLAUDE_BIN` | `claude` from PATH | Absolute path if hooks can't find it |

## Notes

- The 15-minute clock starts at a session's first hook event.
- Hindsight has no auth by default; don't expose the REST API beyond a trusted network.
- Transcript content is sent to Haiku and then to your Hindsight server. The prompt tells Haiku to omit secrets, but that is not a guarantee.
- Debug: `~/.claude/hindsight-snapshots/log.txt`. Quick test: `HS_SNAPSHOT_INTERVAL=60`.
- Remote machines: Hindsight's `/v1` must be reachable (Tailscale Serve route or SSH tunnel to port 8888).

## Uninstall

Remove the three hook entries and `HINDSIGHT_*` env from `~/.claude/settings.json`, then delete
`~/.claude/hooks/hindsight_snapshot.py` and `~/.claude/hindsight-snapshots/`.

MIT licensed.
