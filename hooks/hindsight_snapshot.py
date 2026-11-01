#!/usr/bin/env python3
"""Claude Code hook: every INTERVAL seconds of an active session, spawn a Haiku
summarizer over the new transcript slice and retain the result in Hindsight.

Wired to UserPromptSubmit + PostToolUse + Stop. The hook itself is a cheap
timestamp check; the real work runs in a detached worker (`--worker`).
"""
import fcntl, json, os, shutil, socket, subprocess, sys, time, urllib.request
from pathlib import Path

INTERVAL = int(os.environ.get("HS_SNAPSHOT_INTERVAL", 15 * 60))
HINDSIGHT = os.environ.get("HINDSIGHT_URL", "http://127.0.0.1:8888")
BANK = os.environ.get("HINDSIGHT_BANK", "brain")
MODEL = os.environ.get("HS_SNAPSHOT_MODEL", "haiku")
MAX_CHARS = 60_000
CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
STATE_DIR = Path.home() / ".claude" / "hindsight-snapshots"
LOG = STATE_DIR / "log.txt"

PROMPT = """You are snapshotting a Claude Code working session for long-term memory.
Below is a transcript slice (user / assistant / tool activity). Write a compact,
self-contained snapshot (max ~250 words) in plain prose + short bullets:
- Goal: what the user is trying to accomplish
- Done: concrete changes/findings (file paths, commands, decisions, why)
- State: where things stand right now, open problems, next step
- Durable facts/preferences learned (only if any)
Rules: no preamble, no secrets/tokens/passwords, no speculation. If the slice
contains nothing meaningful, output exactly: SKIP"""


def log(msg):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"{time.strftime('%F %T')} {msg}\n")


def render(transcript, start_line):
    """Return (text, total_lines) for transcript lines after start_line."""
    out, n = [], 0
    with open(transcript) as f:
        for n, line in enumerate(f, 1):
            if n <= start_line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            msg = e.get("message") or {}
            role = msg.get("role") or e.get("type")
            c = msg.get("content")
            if role not in ("user", "assistant") or c is None:
                continue
            if isinstance(c, str):
                out.append(f"[{role}] {c[:2000]}")
                continue
            for b in c:
                t = b.get("type")
                if t == "text":
                    out.append(f"[{role}] {b['text'][:2000]}")
                elif t == "tool_use":
                    out.append(f"[tool_use] {b.get('name')} {json.dumps(b.get('input'))[:300]}")
                elif t == "tool_result":
                    r = b.get("content")
                    r = r if isinstance(r, str) else json.dumps(r)
                    out.append(f"[tool_result] {r[:300]}")
    text = "\n".join(out)
    return text[-MAX_CHARS:], n


def worker(session_id, transcript, cwd):
    sf = STATE_DIR / f"{session_id}.json"
    st = json.loads(sf.read_text()) if sf.exists() else {"line": 0}
    text, total = render(transcript, st["line"])
    if len(text) < 500:
        log(f"{session_id[:8]} slice too small, skipping")
        return
    env = {**os.environ, "HS_SNAPSHOT_CHILD": "1"}
    r = subprocess.run(
        [CLAUDE, "-p", PROMPT, "--model", MODEL, "--tools", "",
         "--no-session-persistence", "--max-turns", "1"],
        input=f"Project dir: {cwd}\n\n{text}", capture_output=True, text=True,
        timeout=300, env=env, cwd=str(STATE_DIR))
    summary = r.stdout.strip()
    if r.returncode != 0 or not summary:
        log(f"{session_id[:8]} haiku failed rc={r.returncode} {r.stderr[:200]}")
        return
    if summary == "SKIP":
        st["line"] = total
        sf.write_text(json.dumps(st))
        return
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    body = {"items": [{
        "content": f"Claude Code session snapshot ({cwd}):\n{summary}",
        "context": "claude-code session snapshot",
        "document_id": f"cc-{session_id}-{int(time.time())}",
        "timestamp": ts,
        "tags": ["claude-code", "snapshot", f"host:{socket.gethostname()}", f"project:{os.path.basename(cwd) or 'root'}"],
    }], "async": True}
    req = urllib.request.Request(
        f"{HINDSIGHT}/v1/default/banks/{BANK}/memories",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        log(f"{session_id[:8]} retained HTTP {resp.status} ({len(summary)} chars)")
    st["line"] = total
    sf.write_text(json.dumps(st))


def hook():
    if os.environ.get("HS_SNAPSHOT_CHILD"):
        return
    data = json.load(sys.stdin)
    sid, tp = data.get("session_id"), data.get("transcript_path")
    if not sid or not tp:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = STATE_DIR / f"{sid}.stamp"
    with open(STATE_DIR / f"{sid}.lock", "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        now = time.time()
        if not stamp.exists():           # first event: start the clock
            stamp.write_text(str(now))
            return
        if now - float(stamp.read_text()) < INTERVAL:
            return
        stamp.write_text(str(now))       # claim this window before spawning
    subprocess.Popen(
        [sys.executable, __file__, "--worker", sid, tp, data.get("cwd", "")],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--worker":
            worker(*sys.argv[2:5])
        else:
            hook()
    except Exception as ex:
        log(f"error: {ex!r}")
    sys.exit(0)
