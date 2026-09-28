# qb2 ops dashboard (`/dash`) — the glance

A read-only HTML page answering one question: **is pi working right now?**
stdlib Python, ~330 lines, no LLM in the render path — every number is read from
systemd, /proc, session files, git, the board and the ledger at request time.
Auto-refresh 15s, GET-only. Runs public (no login) per operator choice — access control sits at the tunnel/LAN layer; the server keeps an `_authed()` hook if auth is ever re-wanted.

What it shows, top to bottom:

- **Status chips**: driver (unit + heartbeat age + window time left), pi worker
  (WORKING/QUIET/STALLED from the newest episode's session mtime — the liveness
  ground truth), Flash-Next serve (health + tok/s), exl3q convert (log freshness),
  phone bridge / ttyd / tunnel units, plus a red banner when a driver alert is
  fresh or the heartbeat goes stale while the window flag is live.
- **Driver log tail** — every judge decision, escalation, stall kill, alert.
- **git tails** of the worker tree and the contrib tree (landed commits).
- **Experiment ledger tail** — the A/B history with keep/discard/published.
- **KANBAN tail** — the live handoff (`turn-N: landed — NEXT: ...`).
- **pi stderr tail** — what the worker said to stderr before dying.

Setup:

```bash
mkdir -p ~/dash && cp setup/bridge/dash-server.py ~/dash/server.py
date -d 'tomorrow 08:00' +%s > ~/dash/window_end   # driver window end (unix s)
DASH_PORT=7015 systemd-run --user --unit=qb2-dash \
  env DASH_PORT=7015 python3 ~/dash/server.py
# tunnel: route <host>/dash.* -> http://localhost:7015 BEFORE any catch-all
# auth: none by default (public); wire the _authed hook if you want Basic auth
```

Tunable via env: `DASH_PORT`, `DASH_SESS_DIR`, `DASH_CONVERT_PID`.

## Exposure note (28 Sep revision)

The original install reused the ttyd Basic credential; the operator later chose a
login-free dash, the removal of both SSH tunnel routes, and closing sshd (22/2222).
Remaining public surface: `/dash` (read-only, no secrets on the page) and the
auth-gated model API. If you expose a dashboard without login, keep it read-only and
assume the URL is public — the page is designed to leak topology only to someone who
already knows the hostnames.
