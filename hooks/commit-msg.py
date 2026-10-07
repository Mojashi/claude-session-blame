#!/usr/bin/env python3
"""git commit-msg hook.

For every staged file, find the Claude Code sessions that touched it after the
file's last commit, and add one `Claude-Session: <id>` trailer per session.

Runs as commit-msg (after the editor), not prepare-commit-msg: a trailer added
before the editor would make an emptied message non-empty, so "clear the message
to abort" would stop working. Here an empty message is left alone.
Never blocks the commit: any failure exits 0 silently.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def is_empty_message(text):
    """Mirror git's own check: ignore comment lines and everything below the scissors line."""
    try:
        char = git("config", "core.commentChar").decode().strip() or "#"
    except subprocess.CalledProcessError:
        char = "#"
    if char == "auto":
        char = "#"
    scissors = f"{char} ------------------------ >8 ------------------------"
    for line in text.splitlines():
        if line == scissors:
            break
        if line.strip() and not line.startswith(char):
            return False
    return True


def main(msg_file):
    with open(msg_file, encoding="utf-8") as f:
        existing = f.read()
    if is_empty_message(existing):
        return

    claude_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    log = os.path.join(claude_dir, "touch-log.jsonl")
    if not os.path.exists(log):
        return

    top = git("rev-parse", "--show-toplevel").decode().strip()
    staged = [p.decode("utf-8", "surrogateescape")
              for p in git("diff", "--cached", "--name-only", "-z").split(b"\0") if p]
    if not staged:
        return
    # realpath of staged file -> commit time of its last commit (0 if never committed)
    since = {}
    has_head = subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"],
                              stdout=subprocess.DEVNULL).returncode == 0
    for rel in staged:
        out = git("log", "-1", "--format=%ct", "--", rel).decode().strip() if has_head else ""
        since[os.path.realpath(os.path.join(top, rel))] = int(out) if out else 0

    sessions, real = [], {}
    with open(log, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                raw, session = e["file"], e["session"]
                ts = datetime.strptime(e["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            except (ValueError, KeyError, TypeError):
                continue
            if not raw or not session:
                continue
            p = real.get(raw)
            if p is None:
                p = real[raw] = os.path.realpath(raw)
            if p in since and ts > since[p] and session not in sessions:
                sessions.append(session)
    if not sessions:
        return

    args = []
    for s in sessions:
        if f"Claude-Session: {s}" not in existing:
            args += ["--trailer", f"Claude-Session: {s}"]
    if args:
        subprocess.run(["git", "interpret-trailers", "--in-place", *args, msg_file], check=False)


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception:
        pass
    sys.exit(0)
