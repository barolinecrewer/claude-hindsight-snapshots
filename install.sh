#!/usr/bin/env bash
# Installs the snapshot hook into ~/.claude and merges hooks into settings.json.
# Usage: HINDSIGHT_URL=http://127.0.0.1:8888 ./install.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
command -v python3 >/dev/null || { echo "python3 required"; exit 1; }
command -v claude  >/dev/null || echo "warning: 'claude' not on PATH (set CLAUDE_BIN)"

mkdir -p ~/.claude/hooks
install -m 755 "$here/hooks/hindsight_snapshot.py" ~/.claude/hooks/hindsight_snapshot.py

HINDSIGHT_URL="${HINDSIGHT_URL:-http://127.0.0.1:8888}" HINDSIGHT_BANK="${HINDSIGHT_BANK:-brain}" python3 - <<'EOF'
import json, os, pathlib
p = pathlib.Path.home() / ".claude" / "settings.json"
s = json.loads(p.read_text()) if p.exists() else {}
cmd = {"type": "command", "command": "python3 ~/.claude/hooks/hindsight_snapshot.py", "timeout": 10}
for ev in ("UserPromptSubmit", "PostToolUse", "Stop"):
    groups = s.setdefault("hooks", {}).setdefault(ev, [])
    if not any(h.get("command") == cmd["command"] for g in groups for h in g.get("hooks", [])):
        groups.append({"hooks": [cmd]})
env = s.setdefault("env", {})
env.setdefault("HINDSIGHT_URL", os.environ["HINDSIGHT_URL"])
env.setdefault("HINDSIGHT_BANK", os.environ["HINDSIGHT_BANK"])
p.write_text(json.dumps(s, indent=2))
print("updated", p)
EOF
echo "Done. Test: curl -s \$HINDSIGHT_URL/health   Log: ~/.claude/hindsight-snapshots/log.txt"
