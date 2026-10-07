#!/usr/bin/env python3
"""Claude Code hook: record which session touched which file.

Appends one JSON line per touched file to $CLAUDE_CONFIG_DIR/touch-log.jsonl:
  {"ts", "session", "transcript", "cwd", "tool", "file"}

  PostToolUse  Edit|Write|MultiEdit|NotebookEdit   exact: the path is in the tool input
  PreToolUse   Bash                                snapshot `git status` (+ mtime/size)
  PostToolUse(Failure) Bash                        diff against the snapshot; every file
                                                   that changed is logged with tool "Bash"

Bash attribution is inferred: a file another process changed while the command ran is
attributed to this session too. Only files `git status` reports are seen (tracked
changes and untracked files in the repo of the session's cwd; ignored files and files
outside a repo are not).

Never blocks the tool call: any failure exits 0 silently.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
LOG = os.path.join(CLAUDE_DIR, "touch-log.jsonl")
PENDING = os.path.join(CLAUDE_DIR, "session-blame", "pending")
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def append(event, tool, files):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = "".join(json.dumps({
        "ts": ts,
        "session": event.get("session_id"),
        "transcript": event.get("transcript_path"),
        "cwd": event.get("cwd"),
        "tool": tool,
        "file": f,
    }, ensure_ascii=False) + "\n" for f in files)
    if lines:
        # One O_APPEND write per call so concurrent sessions don't interleave lines.
        fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, lines.encode("utf-8"))
        finally:
            os.close(fd)


def snapshot(cwd):
    """{absolute path: [mtime_ns, size] or None if missing} for files git status reports."""
    try:
        top = subprocess.check_output(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                                      stderr=subprocess.DEVNULL).decode().strip()
        out = subprocess.check_output(
            ["git", "--no-optional-locks", "-C", top, "status", "--porcelain=v1", "-z", "-uall"],
            stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    entries, snap, i = out.split(b"\0"), {}, 0
    while i < len(entries):
        e = entries[i].decode("utf-8", "surrogateescape")
        i += 1
        if len(e) < 4:
            continue
        if e[0] in "RC":
            i += 1  # skip the rename source path
        p = os.path.join(top, e[3:])
        try:
            st = os.stat(p)
            snap[p] = [st.st_mtime_ns, st.st_size]
        except OSError:
            snap[p] = None
    return snap


def pending_path(event):
    return os.path.join(PENDING, f"{event.get('session_id')}-{event.get('tool_use_id')}.json")


def before_bash(event):
    snap = snapshot(event.get("cwd") or os.getcwd())
    if snap is None:
        return
    os.makedirs(PENDING, exist_ok=True)
    # Drop snapshots whose PostToolUse never came (interrupted calls).
    now = time.time()
    for name in os.listdir(PENDING):
        p = os.path.join(PENDING, name)
        try:
            if now - os.path.getmtime(p) > 86400:
                os.remove(p)
        except OSError:
            pass
    with open(pending_path(event), "w", encoding="utf-8") as f:
        json.dump(snap, f)


def after_bash(event):
    path = pending_path(event)
    try:
        with open(path, encoding="utf-8") as f:
            before = json.load(f)
    except FileNotFoundError:
        return
    os.remove(path)
    after = snapshot(event.get("cwd") or os.getcwd()) or {}
    changed = []
    for p, state in after.items():
        if before.get(p, "absent") != state:
            changed.append(p)
    # Files that left `git status` because they were restored or deleted-and-committed
    # are not edits we can see; files that vanished from disk while listed are.
    for p, state in before.items():
        if p not in after and state is not None and not os.path.exists(p):
            changed.append(p)
    append(event, "Bash", sorted(changed))


def main():
    event = json.load(sys.stdin)
    name, tool = event.get("hook_event_name"), event.get("tool_name")
    if tool == "Bash":
        if name == "PreToolUse":
            before_bash(event)
        elif name in ("PostToolUse", "PostToolUseFailure"):
            after_bash(event)
    elif tool in WRITE_TOOLS and name == "PostToolUse":
        tool_input = event.get("tool_input") or {}
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if path:
            append(event, tool, [path])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
