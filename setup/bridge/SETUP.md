# pi-chat — phone bridge to your pi agent

A ~170-line Python stdlib server that puts your pi agent on a phone browser: per-
conversation long-lived `pi --mode rpc` children (full context per conversation),
header-key auth, no dependencies.

Files: `server.py` (the bridge), `index.html` (the chat UI, served at `/pi-chat`).

## Setup

```bash
mkdir -p ~/pi-chat/sessions ~/pi-chat/state
cp server.py index.html ~/pi-chat/
echo -n "$(openssl rand -hex 24)" > ~/pi-chat/.auth_token
chmod 600 ~/pi-chat/.auth_token
```

## Run (systemd user unit, survives logout)

```ini
# ~/.config/systemd/user/pi-chat.service
[Unit]
Description=pi-chat: phone bridge to the pi coding agent

[Service]
ExecStart=/usr/bin/python3 %h/pi-chat/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload && systemctl --user enable --now pi-chat.service
loginctl enable-linger $USER    # units survive logout — do this once
```

## Use

- Web UI: `http://<box-ip>:7011/pi-chat` — the UI sends `X-Chat-Key` once entered.
- API: `POST /pi-chat/api/send` with `{"conv":"<alphanumeric-id>","message":"..."}`
  and header `X-Chat-Key: <token>`; `GET /pi-chat/api/health` returns
  `{"ok":true,"conversations":N}` when authed.
- Health is 401 without the key — that's the unauthenticated surface, by design.
- Bind is 0.0.0.0 (LAN); put it behind whatever exposure layer you trust (tailscale,
  LAN-only, an authed tunnel path). We run it LAN-only after deliberately removing
  our public tunnel — pick your own threat model here.

## Housekeeping lessons (from running it daily)

- The bridge spawns `pi --mode rpc --session-id <conv>` per conversation; a dead child
  is respawned on the next send. `(pi rpc child exited — send again to restart)` in a
  reply almost always means an **extension load failure** — check
  `state/pi-stderr.log` before blaming the network.
- Auth token is read at startup — restart after regenerating.
- The deep-probe pattern in `watchdog/example-watchdog.sh` (send a trivial prompt
  through the bridge, expect an exact reply) exercises the full chain: bridge → pi
  child spawn → provider → response. That's the monitor that catches a dead provider
  key at 3 a.m. instead of a silent zombie.

## Why a bridge at all

The overnight loop means the worker is doing things you'll want to poke at from a
phone: ask what changed, nudge it, read the board. pi's native UI assumes a terminal;
this gives the same agent a chat surface with per-conversation memory (each conv id is
a persistent pi session). Pair it with the ttyd tmux bridge (`ttyd -W -c <cred> -- tmux
new-session -A -s pi-chat`) for a full terminal from the browser — same tmux session
the fallback shell uses, so phone and box see the same terminal.
