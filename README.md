# tt-automatic

**An overnight autonomous agent loop that actually survives the night.** Battle-tested
operator for keeping a coding agent (pi, Claude Code, Codex — anything with a CLI loop)
working unattended for 12+ hours: episodic turns, mechanical quality judging,
escalation instead of halting, stall reaping, and a tabular experiment ledger.

Name origin: the loop drives itself, and the human gets the driving report.

This is not a framework or an SDK — it's **four small bash scripts and two contracts**
that were built the hard way: by failing overnight, dissecting the corpse, and fixing
the root cause. It runs one real workload (Tenstorrent Blackhole LLM inference
optimization, 125B MoE) and has landed real wins unattended: a +49% prefill throughput
change, a leaderboard publication, two closed profiling tickets, and a
no-go decision backed by numbers — all while the operator slept.

## The war story (why this exists)

Night one, a naive "spawn agent, feed it the goal, let it run" loop:

- **00:35** — the loop's ssh driver session dies (phone terminal crashed). Agent dead
  in the water, mid-edit, with uncommitted changes in the production tree.
- Recovered, relaunched with a `while true` auto-continue driver.
- The agent then did **1.5 hours of genuinely excellent work**: closed an attribution
  ticket (host cost = 0.113% of the wall → killed a whole workstream with numbers),
  measured the per-stage device split, landed a +49% prefill win, published it to a
  leaderboard, and proved the inference pass is fully serialized.
- **21:08** — the driver *itself* false-halted (it counted slow agent restarts as
  "unproductive turns"; three strikes and it exited).
- **21:55** — the last working turn finished writing its summary… and then hung forever
  on a stalled provider stream (upstream agent bug, session alive, turn never ends).
- **05:00** — operator wakes up. **Seven hours of dead air.** The agent didn't crash.
  The *supervision* did.

Root causes found: (1) one mega-session makes every agent restart slower and every
quality judgment noisier; (2) halting on "unproductive" is wrong — you must escalate;
(3) a turn that *ends its work but never exits* looks alive forever; (4) nobody alerts
the human when the supervisor itself dies.

tt-automatic is the fix for all four.

## What's in the box

```
driver/
  overnight-driver.sh   the supervisor loop (bash, ~160 lines, no dependencies)
  episode-launcher.sh   spawns ONE agent episode (fresh context) with the re-orient prompt
  pane-wrapper.sh       tmux pane wrapper: env hygiene + turn exit codes + logging
watchdog/
  example-watchdog.sh   standing 30-min cron: relays alerts, checks chain liveness + heartbeat
contracts/
  GOAL_BRIEF.example.md the human-authored contract (objective, constraints, stop conditions)
experiments/
  experiments.example.tsv the tabular experiment ledger (keep/discard/published)
setup/
  pi/                   full pi agent install: provider config, operator system-prompt
                        template, tools extension (gh search fix), pitfalls
  bridge/               pi-chat: ~170-line stdlib phone bridge to the agent + UI
  hermes/               the supervisor platform wiring: watchdog cron, alert relay,
                        division of labor (worker / shift boss / chief of staff)
```

## How the loop works

**Episodic turns (Ralph Wiggum / nightcrawler pattern).** Every episode is a *fresh*
agent context. All state lives on disk:

- `GOAL_BRIEF.md` — the contract the human wrote (never touched by the agent)
- the board (KANBAN) — the agent appends `turn-N: <landed> — NEXT: <what>` every episode;
  the next episode orients from the tail and picks up cold
- git — every landed increment is a commit

This kills the mega-session problems: no context replay growing every restart, no
10-minute boots, and each episode's quality signal is clean.

**Mechanical quality judging — no LLM judge.** After each episode ends, the driver
checks four deterministic signals: git commit-count delta, board-file md5 delta,
experiment-ledger md5 delta, session-byte delta. Plus a loop detector (identical
final text on consecutive episodes). No second LLM, no cost, no judge-model
hallucinating progress.

**Escalate, don't halt.** Three unproductive episodes in a row does NOT stop the loop.
It spawns a *re-orient episode*: a fresh context told explicitly "your recent episodes
were unproductive — re-read state and pick a DIFFERENT ticket." Capped (default 6
escalations), then and only then it stops and alerts.

**Stall reaping.** A running episode whose transcript goes silent for 30 minutes gets
killed and respawned. This is the workaround for the known upstream failure mode where
a provider stream stalls and the agent hangs forever (session frozen 25–109 minutes
upstream; 7 hours here). Until your agent's runtime ships an inactivity timeout, an
external reaper is the only cure.

**Boot-race awareness.** A freshly respawned agent replays its session before writing
anything. Naive judges read that as "zero progress" and false-trip the halt. The driver
skips the first judgment after every respawn and re-baselines the size snapshot.

**e/acc decision policy (optional).** The agent is told to emit `USER_DECISION_NEEDED:
<question>` instead of blocking on the human. The driver auto-answers with the most
aggressive forward option that doesn't violate the contract's never-break-known-good
guard, relays every decision to the human's channel, and halts only if the same
decision class repeats three times. You see every decision it made, never silently.

**Alert relay without a second scheduler.** The driver writes alert files; your
existing watchdog cron relays them (report-once, then ack). The watchdog also watches
a driver heartbeat against a window-live flag — if the supervisor itself dies, you get
a ping within the hour instead of silence until morning.

## Why it works better than the alternatives

Credit where due — these informed the design:

- **Ralph Wiggum** (ghuntley): `while :; do agent; done` with fresh context and repo-as-state.
  *tt-automatic adds:* judging (Ralph re-prompts blindly), escalation, stall reaping,
  boot-race handling, and alerting. Ralph also has no answer for a turn that never ends.
- **nightcrawler-style episodic supervisors**: same episodic + handoff idea.
  *tt-automatic adds:* the mechanical (not LLM) judge, ledger-gated productivity, and
  the e/acc auto-answer — nightcrawler-style setups still stop and wait for a human
  when an episode degrades.
- **claudekeeper / vibe-coding-auto-resume / claude-tmux-dog**: tmux prompt-scheduling
  daemons with restart and auto-nudge. *tt-automatic adds:* quality *judging* between
  prompts (they schedule blindly), a stop-condition vocabulary the agent can trigger
  (`USER_DECISION_NEEDED`, `OVERNIGHT_WINDOW_COMPLETE`), and per-turn exit-code telemetry
  (turn died how? the wrapper knows).
- **Plain cron + `--continue`**: fires a prompt every N minutes forever, burns provider
  cycles on degenerate loops, can't tell work from survival.

The one-sentence difference: **everyone else automates the prompt; tt-automatic
automates the judgment.** The loop doesn't just keep the agent running — it keeps the
agent *honest* (ledger, board, git), *moving* (escalation), and *accountable* (every
auto-decision relayed).

## The contracts (the actual magic)

The scripts are 400 lines of bash. The system works because of two documents:

1. **The goal brief** (human-authored, frozen during the run): objective, constraints
   (never-break-known-good rollback tags), validation protocol per change, publish-only-
   winners rule, explicit stop conditions. The agent's creativity happens *inside* it.
2. **The disk handoff contract**: every episode must append `turn-N: <landed> — NEXT:
   <what>` to the board and commit. Episodes are stateless; the board is the brain.
3. **The experiment ledger** (pattern credit: `bro4all/autoresearch-tenstorrent`, the
   TT port of karpathy/autoresearch): every benchmarked A/B gets a TSV row —
   `commit | area | metric | value | unit | status keep/discard/crash/published |
   run_id | description`. Never redefine a metric, never compare across profiles.
   The driver counts ledger growth as real work, so benchmark-only episodes aren't
   judged "unproductive."

## First-night results (real, on a Tenstorrent QuietBox 2 / 4× p300c)

- Attribution ticket closed: host-side launch cost = **0.113%** of the inference wall →
  a whole "rewrite the host loop in C++/Rust" workstream killed with numbers.
- Per-stage device split measured: verify 40.5 ms (74%) / draft 8.7 / commit 3.4 / ple 1.6.
- Decode pass proven fully serialized (trace-replay sum = pipelined wall) → next levers
  are trace-level cuts and fewer passes, not pipelining.
- Prefill `--long-chunks` win: 518 → **771 tok/s synthetic (+49%)**, decode wash, pins
  green, published to a leaderboard: **+37% prefill over the previous posted entry**.
- All of it landed between 20:52 and 21:55 — one hour, unattended, while the operator
  watched a phone.

## Quick start

```bash
git clone https://github.com/deaiafdeling/tt-automatic
cd tt-automatic

# 1. Write your contract (start from the example)
cp contracts/GOAL_BRIEF.example.md ~/GOAL_BRIEF.md && $EDITOR ~/GOAL_BRIEF.md

# 2. Point the scripts at your tree
export TTA_HOME=$HOME      # where your repo / board / sessions live

# 3. Run the driver under a systemd user unit (survives logout) or nohup
systemd-run --user --unit=overnight-driver \
  driver/overnight-driver.sh "tomorrow 08:00"

# 4. (optional) wire the watchdog into cron for alert relaying + liveness
```

Requirements: bash, tmux, systemd (user units), git, and a CLI coding agent. The
defaults assume `pi` (earendil-works) with `--session-id` episodic sessions; adapting
to Claude Code / Codex is a one-line change in `episode-launcher.sh`.

## Honest limitations

- bash + systemd + tmux: Linux-first, no Windows/macOS story.
- The judge is heuristic: commit/board/ledger/bytes — it can't read the *quality* of
  prose. It catches stalls and loops, not bad ideas. That's what the goal brief is for.
- The e/acc auto-answer is a policy choice, not a default: read `overnight-driver.sh`
  and decide if you want it.
- One loop per box, one board, one mesh. It's operator machinery, not a platform.

## License

MIT.
