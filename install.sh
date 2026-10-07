#!/usr/bin/env bash
# claude-session-blame installer.
#
#   ./install.sh                       install the Claude Code hook and the `cls` command
#   ./install.sh --bin-dir DIR         put `cls` in DIR instead of ~/.local/bin
#   ./install.sh --git-hook [REPO]     add Claude-Session trailers to commits in REPO (default: current repo)
#   ./install.sh --uninstall           remove the hook and `cls` (the log is kept)
#
# Re-running is safe: every step is idempotent.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DEST="$CLAUDE_DIR/session-blame"
SETTINGS="$CLAUDE_DIR/settings.json"
BIN_DIR="$HOME/.local/bin"
MODE=install
REPO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --bin-dir) BIN_DIR="$2"; shift 2 ;;
    --git-hook) MODE=git-hook; if [ $# -gt 1 ] && [ "${2#-}" = "$2" ]; then REPO="$2"; shift; fi; shift ;;
    --uninstall) MODE=uninstall; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

# Add / remove our PostToolUse hook in settings.json, leaving everything else untouched.
edit_settings() {  # $1 = add | remove
  python3 - "$SETTINGS" "$DEST/hooks/log-touch.py" "$1" <<'EOF'
import json, os, shlex, shutil, sys
path, script, action = sys.argv[1:]
command = shlex.quote(script)
WANT = [  # (event, matcher)
    ("PreToolUse", "Bash"),
    ("PostToolUse", "Edit|Write|MultiEdit|NotebookEdit|Bash"),
    ("PostToolUseFailure", "Bash"),
]
settings = {}
if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        settings = json.load(f)
hooks = settings.setdefault("hooks", {})


def ours(h):
    return "session-blame/hooks/log-touch.py" in h.get("command", "")


# Always strip our entries first, then re-add: upgrades change matchers/events.
before = json.dumps(hooks, sort_keys=True)
for event in list(hooks):
    groups = hooks[event]
    for g in groups:
        g["hooks"] = [h for h in g.get("hooks", []) if not ours(h)]
    groups[:] = [g for g in groups if g.get("hooks")]
    if not groups:
        del hooks[event]
if action == "add":
    for event, matcher in WANT:
        hooks.setdefault(event, []).append(
            {"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": 10}]})
if not hooks:
    del settings["hooks"]
if json.dumps(settings.get("hooks", {}), sort_keys=True) == before:
    print(f"  hooks already up to date in {path}")
    sys.exit(0)
backup = os.path.exists(path)
if backup:
    shutil.copy2(path, path + ".bak")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write("\n")
verb = "updated hooks in" if action == "add" else "removed hooks from"
print(f"  {verb} {path}" + (f" (backup: {path}.bak)" if backup else ""))
EOF
}

case "$MODE" in
  install)
    echo "Installing claude-session-blame"
    mkdir -p "$DEST/hooks" "$DEST/bin" "$BIN_DIR"
    install -m 755 "$SRC/hooks/log-touch.py" "$SRC/hooks/commit-msg.py" "$DEST/hooks/"
    install -m 755 "$SRC/bin/cls" "$DEST/bin/cls"
    echo "  copied files to $DEST"
    ln -sf "$DEST/bin/cls" "$BIN_DIR/cls"
    echo "  linked $BIN_DIR/cls"
    edit_settings add
    case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "  note: $BIN_DIR is not on your PATH" ;; esac
    echo
    echo "Done. Claude Code now logs the files each session touches to $CLAUDE_DIR/touch-log.jsonl."
    echo "Try: cls   |   cls -g   |   cls -s <session-id>"
    echo "Optional: ./install.sh --git-hook  (adds Claude-Session trailers to commits in this repo)"
    ;;

  git-hook)
    [ -x "$DEST/hooks/commit-msg.py" ] || { echo "run ./install.sh first" >&2; exit 1; }
    dir="$(git -C "${REPO:-.}" rev-parse --path-format=absolute --git-path hooks)"
    target="$dir/commit-msg"
    mkdir -p "$dir"
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$DEST/hooks/commit-msg.py" ]; then
      echo "already installed: $target"
    elif [ -e "$target" ]; then
      echo "$target already exists; not overwriting. Call ours from it instead:" >&2
      echo "  \"$DEST/hooks/commit-msg.py\" \"\$@\"" >&2
      exit 1
    else
      ln -s "$DEST/hooks/commit-msg.py" "$target"
      echo "installed: $target"
    fi
    ;;

  uninstall)
    echo "Uninstalling claude-session-blame"
    edit_settings remove
    if [ -L "$BIN_DIR/cls" ] && [ "$(readlink "$BIN_DIR/cls")" = "$DEST/bin/cls" ]; then
      rm "$BIN_DIR/cls"; echo "  removed $BIN_DIR/cls"
    fi
    rm -rf "$DEST"; echo "  removed $DEST"
    echo "Kept $CLAUDE_DIR/touch-log.jsonl. Git hooks installed with --git-hook now point at"
    echo "a missing file; delete each repo's .git/hooks/commit-msg link."
    ;;
esac
