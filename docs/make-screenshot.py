#!/usr/bin/env python3
"""Regenerate docs/watch.svg: run `cls -w` against a synthetic log in a pty and draw the screen.

    pip install pyte   # once
    python3 docs/make-screenshot.py

Uses made-up sessions only, so the screenshot never shows a real project.
"""

import fcntl
import json
import os
import pty
import random
import select
import struct
import sys
import tempfile
import termios
import time
from datetime import datetime, timezone
from html import escape

import pyte

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLS, ROWS = 118, 36
SESSIONS = [
    ("3f9a1c2e-0b7d-4e55-9a10-6c1d2e3f4a5b", "Add rate limiting to the public API"),
    ("a71c04d9-5e2f-4b8a-8c3d-1e2f3a4b5c6d", "Fix the login redirect loop"),
    ("c2d8e6f1-9a0b-4c1d-8e2f-3a4b5c6d7e8f", "Monthly invoice export"),
    ("5b0e7a93-2c4d-4e6f-8a1b-2c3d4e5f6a7b", "Migrate settings page to new forms"),
    ("e94f2b10-7d8c-4a3b-9c2d-1e0f2a3b4c5d", "Flaky test investigation"),
]
FILES = {
    0: ["src/server/rateLimit.ts", "src/server/rateLimit.test.ts", "src/server/routes.ts", "docs/api.md"],
    1: ["src/client/auth/redirect.ts", "src/client/App.tsx", "src/server/routes.ts", "src/client/auth/session.ts"],
    2: ["src/server/billing/invoice.ts", "src/server/billing/csv.ts", "src/server/billing/invoice.test.ts"],
    3: ["src/client/settings/Form.tsx", "src/client/settings/fields.ts", "src/client/App.tsx"],
    4: ["src/server/billing/invoice.test.ts", "vitest.config.ts"],
}


def build_log(home, repo):
    os.makedirs(os.path.join(repo, ".git"), exist_ok=True)
    rnd, now, lines = random.Random(7), time.time(), []
    os.makedirs(os.path.join(home, "projects"), exist_ok=True)
    for i, (sid, title) in enumerate(SESSIONS):
        transcript = os.path.join(home, "projects", sid + ".jsonl")
        with open(transcript, "w") as f:
            f.write(json.dumps({"type": "ai-title", "aiTitle": title, "sessionId": sid}, separators=(",", ":")) + "\n")
        start = now - rnd.uniform(25, 58) * 60
        end = now - (rnd.uniform(0, 3) if i < 4 else 34) * 60
        for _ in range(rnd.randint(14, 30)):
            t = rnd.uniform(start, end)
            tool = rnd.choice(["Edit", "Edit", "Write", "Bash", "Bash"])
            for f in rnd.sample(FILES[i], rnd.randint(1, 2) if tool == "Bash" else 1):
                lines.append((t, sid, transcript, tool, os.path.join(repo, f)))
    lines.append((now - 2, SESSIONS[0][0], os.path.join(home, "projects", SESSIONS[0][0] + ".jsonl"),
                  "Edit", os.path.join(repo, "src/server/routes.ts")))
    lines.sort()
    with open(os.path.join(home, "touch-log.jsonl"), "w") as f:
        for t, sid, transcript, tool, path in lines:
            f.write(json.dumps({
                "ts": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "t": t,
                "session": sid, "transcript": transcript, "cwd": repo, "tool": tool, "file": path}) + "\n")
    for _, _, _, _, path in lines:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "a").close()


def capture(home, repo):
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(repo)
        os.environ.update(TERM="xterm-256color", CLAUDE_CONFIG_DIR=home, LANG="en_US.UTF-8")
        os.execvp(sys.executable, [sys.executable, os.path.join(ROOT, "bin", "cls"), "-w"])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    end = time.time() + 2.5
    while time.time() < end:
        if select.select([fd], [], [], 0.05)[0]:
            try:
                stream.feed(os.read(fd, 65536))
            except OSError:
                break
    snapshot = [[(c.data, c.fg, c.bg, c.bold, c.reverse) for c in (screen.buffer[y][x] for x in range(COLS))]
                for y in range(ROWS)]
    os.write(fd, b"q")
    while True:  # keep draining, or the child blocks writing its exit sequence into a full pty
        try:
            if select.select([fd], [], [], 0.1)[0] and not os.read(fd, 65536):
                break
        except OSError:
            break
        if os.waitpid(pid, os.WNOHANG)[0]:
            break
    return snapshot


XTERM = {"black": "#1e2127", "red": "#e06c75", "green": "#98c379", "brown": "#e5c07b", "blue": "#61afef",
         "magenta": "#c678dd", "cyan": "#56b6c2", "white": "#abb2bf", "default": None}


def color(name, default):
    if name in XTERM:
        return XTERM[name] or default
    if len(name) == 6:
        return "#" + name
    return default


def to_svg(screen):
    cw, ch, pad = 8.4, 18, 14
    fg0, bg0 = "#c8ccd4", "#16181d"
    w, h = COLS * cw + pad * 2, ROWS * ch + pad * 2 + 26
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
           f'font-family="SF Mono, Menlo, Consolas, monospace" font-size="14">',
           f'<rect width="100%" height="100%" rx="10" fill="{bg0}"/>',
           *[f'<circle cx="{pad + 6 + i * 18}" cy="14" r="6" fill="{c}"/>'
             for i, c in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"])]]
    for y in range(ROWS):
        line = screen[y]
        x = 0
        while x < COLS:
            data, cfg, cbg, bold, reverse = line[x]
            fg, bg = color(cfg, fg0), color(cbg, None)
            if reverse:
                fg, bg = bg or bg0, fg
            px, py = pad + x * cw, pad + 26 + y * ch
            span = 2 if x + 1 < COLS and line[x + 1][0] == "" else 1
            if bg:
                out.append(f'<rect x="{px:.1f}" y="{py - 13:.1f}" width="{cw * span + .5:.1f}" height="{ch}" fill="{bg}"/>')
            if data.strip():
                weight = ' font-weight="bold"' if bold else ""
                out.append(f'<text x="{px:.1f}" y="{py:.1f}" fill="{fg}"{weight}>{escape(data)}</text>')
            x += span
    out.append("</svg>")
    return "\n".join(out)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = os.path.join(tmp, "claude"), os.path.join(tmp, "acme-app")
        build_log(home, repo)
        svg = to_svg(capture(home, repo))
    path = os.path.join(ROOT, "docs", "watch.svg")
    with open(path, "w") as f:
        f.write(svg)
    print("wrote", path)


if __name__ == "__main__":
    main()
