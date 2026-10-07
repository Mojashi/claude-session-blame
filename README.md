# claude-session-blame

`git blame` for Claude Code sessions: find out **which Claude Code session touched which file**.

When several Claude Code sessions work in the same checkout, the working tree fills up
with uncommitted changes and nobody knows whose they are. This adds:

- a Claude Code hook that logs every file a session touches to `~/.claude/touch-log.jsonl`
- **`cls`**: `ls` / `git status` with the session that last touched each file
- an optional git hook that stamps commits with `Claude-Session: <id>` trailers

```
$ cls -g
 M src/server/routes.ts      3m ago   01b3e9b2  Add rate limiting to the API
 M src/client/App.tsx        12m ago ~5c21fc03  Fix the login redirect  (+1)
?? src/server/billing.ts     1h ago   d4aac65c  Monthly invoice export
 M package.json
```

The title is the session's name in Claude Code (custom title, else the auto-generated
one). The same session always gets the same color.

## Install

Requires Python 3.8+ and git. macOS and Linux.

```sh
git clone https://github.com/Mojashi/claude-session-blame
cd claude-session-blame
./install.sh                 # hooks into ~/.claude/settings.json, puts `cls` in ~/.local/bin
./install.sh --git-hook PATH # optional, per repo: Claude-Session trailers on commits
```

The installer copies its files to `~/.claude/session-blame/` (so the clone can be
deleted), backs up `settings.json` to `settings.json.bak`, and only adds or removes its
own entries. Re-run it after `git pull` to upgrade. `--bin-dir DIR` puts `cls` elsewhere.
`CLAUDE_CONFIG_DIR` is respected.

Hooks are read when a session starts, so restart running sessions (or open `/hooks`) to
pick them up.

## Usage

```sh
cls [-a] [-l] [PATH...]   # list a directory; a directory row shows its newest touch
cls -g [-l]               # files git status reports as changed
cls -s SESSION [PATH]     # every file one session touched (id prefix is enough)
```

- `-l` shows every session that touched the file instead of only the latest (`(+N)`)
- `-a` includes hidden files
- `~` before the session id: the touch was inferred from a Bash command (see below)
- `(deleted)`: the log has it but the file is gone

Output is Japanese when `LANG` starts with `ja`. `NO_COLOR` disables colors.

To pick out your own changes before committing in a shared working tree:

```sh
cls -s 5c21fc03            # the files this session touched
git log --format='%h %s %(trailers:key=Claude-Session,valueonly,separator=%x2C )'
```

## How it works

| Hook | What is recorded |
|---|---|
| `PostToolUse` Edit / Write / MultiEdit / NotebookEdit | the `file_path` from the tool input (exact) |
| `PreToolUse` Bash → `PostToolUse` / `PostToolUseFailure` Bash | files whose mtime/size changed in `git status` while the command ran (inferred, `~`) |
| git `commit-msg` (optional) | for each staged file, sessions that touched it after its last commit → `Claude-Session:` trailers |

Each touch is one JSON line:

```json
{"ts": "2026-10-07T04:49:39Z", "session": "f9190186-…", "transcript": "~/.claude/projects/…/f9190186-….jsonl", "cwd": "/repo", "tool": "Write", "file": "/repo/a.txt"}
```

### Limits

- **Bash attribution is a heuristic.** If another process (another session, your editor,
  a watcher) changes a file while a Bash command runs, that file is attributed to the
  session too. Only files that `git status` lists in the repo of the session's working
  directory are seen. Gitignored files, files outside a repo, and edits after a
  `cd` into another repo are missed. Background commands (`run_in_background`) are only
  observed until they start.
- Touches from before the install are unknown.
- The commit trailer is added in `commit-msg`, so `git commit --no-verify` skips it. An
  emptied commit message still aborts the commit.
- Overhead: one `git status` before and after each Bash call (about 10 ms on a
  mid-sized repo with `--no-optional-locks`, so it never takes the index lock).

The log never leaves your machine. It grows by one line per touched file. Truncate it
whenever you like.

## Uninstall

```sh
./install.sh --uninstall   # removes the hooks and `cls`; keeps touch-log.jsonl
rm .git/hooks/commit-msg   # in each repo where you ran --git-hook
```

---

## 日本語

同じ作業ツリーで複数の Claude Code セッションが並行して動くと、未コミットの変更が「どのセッションのものか」分からなくなります。このツールは、各セッションが触ったファイルを記録し、`cls` で `ls` / `git status` にセッション（ID とタイトル）を付けて表示します。commit には `Claude-Session:` trailer を付けられます。

```sh
./install.sh                 # hook と cls を入れる
./install.sh --git-hook .    # このリポジトリの commit に trailer を付ける
cls -g                       # 変更ファイルにセッションを付けて表示
cls -s <session-id>          # そのセッションが触ったファイル一覧
```

Edit / Write 系のツールは正確に記録されます。Bash 経由の編集（`sed -i`、heredoc、スクリプト）は、実行前後の `git status` の差分から推定し、`~` を付けて表示します。並行して別プロセスが同じリポジトリを書き換えた場合は、そのファイルもこのセッションの分として記録されることがあります。

## License

MIT
