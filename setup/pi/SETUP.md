# pi agent setup (the way we run it)

pi (earendil-works, `@earendil-works/pi-coding-agent`) is the worker agent this loop was
built and battle-tested against. This reproduces our full operator install. The loop
itself only needs `pi` on PATH and a `--session-id` episodic mode — but the operator
quality (domain rules, gh search fix, board tool) is what makes nights productive.

## 1. Install

```bash
npm install -g @earendil-works/pi-coding-agent --ignore-scripts
pi --version          # developed against 0.87.1
```

`~/.local/bin/pi` is the expected location — if npm puts it elsewhere, symlink or adjust
`TTA_HOME/.local/bin` in `driver/episode-launcher.sh` / `driver/pane-wrapper.sh`.

## 2. Provider + model

pi talks to any OpenAI-compatible endpoint. `~/.pi/agent/models.json`:

```json
{
  "providers": {
    "myprovider": {
      "name": "my provider",
      "baseUrl": "https://YOUR-ENDPOINT/v1",
      "api": "openai-completions",
      "apiKey": "YOUR-KEY",
      "models": [{
        "id": "your-model-id",
        "name": "your model",
        "reasoning": true,
        "input": ["text"],
        "contextWindow": 131072,
        "maxTokens": 32768
      }]
    }
  }
}
```

`~/.pi/agent/settings.json`:

```json
{
  "defaultProvider": "myprovider",
  "defaultModel": "myprovider/your-model-id",
  "defaultThinkingLevel": "medium",
  "enableInstallTelemetry": false
}
```

Any long-context reasoning model works. Ours runs a GLM-5.3-class endpoint; pick for
agentic tool-loop reliability over benchmark scores — overnight throughput dies on
provider stalls, and a model that tool-loops cleanly beats a smarter model that stalls.

## 3. The operator system prompt (APPEND_SYSTEM.md)

`~/.pi/agent/APPEND_SYSTEM.md` is appended to pi's system prompt on every episode
(`--append-system-prompt` in the launcher). This is the worker's professional
identity. Copy `setup/pi/APPEND_SYSTEM.template.md` and fill in YOUR domain rules.
Ours (a Tenstorrent hardware bring-up operator) carries:

- **mesh/device discipline** — never touch hardware another process owns; the reset
  ladder; always hand back clean ("serve back UP before the turn ends")
- **read-before-act** — re-orient from files (board tail, git log, reference docs)
  before writing anything, every episode
- **env-staleness check** — read the LIVE environment from /proc before declaring a
  service's state; config files drift from reality
- **commit-before-delegate** — never leave uncommitted work in a tree another process
  (or your own next episode) will touch; commit + board line every landed increment
- **checkout discipline** — child agents get their own worktrees, never the production
  checkout
- **never-break-known-good** — rollback tags and published configs are tripwires

The pattern regardless of domain: the system prompt is the *profession*, the
GOAL_BRIEF is the *job*, the board is the *memory*.

## 4. Tools extension (optional but recommended)

pi extensions are TypeScript in `~/.pi/agent/extensions/<name>/index.ts` registering
tools via `pi.registerTool({...})`. Ours (`setup/pi/tt-tools.ts`) adds four:

- **github_search** — wraps the gh CLI; includes the `repo:owner/name term` fix (gh
  shell-quotes the qualifier into an invalid query; extract it and pass `--repo`).
  Use it before writing any new op/fix: search upstream for existing solutions.
- **web_search** — DuckDuckGo HTML scrape, no API key.
- **fetch_page** — pull a URL as text.
- **kanban** — read/append/tail the board file.

If you skip this, the agent still works with its built-in bash — the extension exists
to make the common operations reliable and cheap.

## 5. Verify the whole chain

```bash
pi -p 'reply with exactly: PI-CHAIN-OK'        # endpoint + key + model
# then from the loop's perspective (what the driver actually runs):
pi --session-id smoke-$(date +%s) \
  --append-system-prompt ~/.pi/agent/APPEND_SYSTEM.md \
  -p 'read the board at ~/tt-contrib/KANBAN.md and reply with its last line'
```

## Pitfalls we hit (all reproduced, all real)

- **Never `nohup`/close pi's stdin** — pi reads stdin even in `-p` print mode; a closed
  fd kills it instantly (`EBADF: bad file descriptor`). Give it a real pty (tmux pane).
- **tmux panes inherit the tmux SERVER's env**, not the spawner's — a pane spawned from
  systemd without `~/.local/bin` gets `env: node: No such file or directory` and every
  respawn dies. The pane wrapper exports PATH itself.
- **`pi -p` is one mega-turn**: it grinds the tool-loop until the model stops, then
  exits. Long unattended runs need the external driver — pi has no scheduler.
- **Session files live under `~/.pi/agent/sessions/<slashified-cwd>/`** — the directory
  encodes where pi ran. Glob across project dirs when hunting a session by id.
- **Liveness ground truth = session jsonl mtime/size**, not stdout or TCP. Session
  grows = alive. Stuck 10+ min = wedged. `pi -p` prints only at turn end.
- **pi upstream #8331**: a stalled provider stream hangs the loop forever (observed
  25–109 min upstream, 7h on our box). Until an inactivity timeout ships, the driver's
  stall reaper is the cure.
- **Extension parse errors surface as `(pi rpc child exited — send again)`** on the
  bridge — check the child's stderr log first, not the network.
