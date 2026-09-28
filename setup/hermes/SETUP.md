# Hermes Agent setup (the supervisor side)

tt-automatic's driver is deliberately dumb — bash, no LLM. On our box the *supervision
platform* around it is [Hermes Agent](https://hermes-agent.nousresearch.com/docs)
(Nous Research), and this doc reproduces how the pieces wire together. Any agent
platform with cron + a chat channel works in this role (the watchdog is just a
script; the "alert relay" is just its stdout).

## Division of labor (the part people get wrong)

- **pi = the worker.** It holds no schedule, no cron, no supervision. It does one
  focused unit of work per episode and ends with a board line. It knows nothing about
  the loop.
- **the driver = the shift boss.** bash. Judges, escalates, reaps, respawns, writes
  alert files. Knows nothing about the work content.
- **Hermes = the chief of staff.** Owns the crons (watchdog, reminders), relays alerts
  to the human's channel, runs the leaderboard/dashboard publishing, and can reach the
  box itself when the human asks questions in chat. It never does the worker's job.

Two agents, one board, zero shared state: the board file and git are the only medium.

## The watchdog cron (Hermes side)

Create `~/.hermes/scripts/pi_watchdog.sh` (see `watchdog/example-watchdog.sh`) and
register it as a **no-agent cron** — the script IS the job, stdout delivers verbatim,
**empty stdout sends nothing** (the silent-when-healthy watchdog pattern):

```bash
# via hermes CLI:
hermes cron add --schedule "every 30m" --name pi-chat watchdog \
  --script pi_watchdog.sh --no-agent
```

The script's contract: silent + exit 0 when healthy; on failure print a short report
(delivered to the user's channel). Sections in our example:

1. systemd user units auto-heal (start inactive ones, re-check)
2. ports actually listening
3. authed health endpoint
4. deep probe — send a trivial prompt THROUGH the real bridge and expect an exact
   reply; a wedged pi child is killed and retried once before alerting. This catches
   the failure mode a port check can't: pi alive, provider dead.
5. driver alert relay — report + ack any fresh alert file (each alert reaches the
   human exactly once)
6. overnight liveness — if the driver declared a live window (flag file) but its
   heartbeat is stale >1h, alert (this is the "supervisor died" alarm)

## Why this beats "give the agent a cron that prompts it"

Hermes-side crons that *prompt* an agent every N minutes are the blind-scheduler
anti-pattern: no judging, no escalation, provider cycles burned on degenerate loops.
The split we landed on after two failed nights:

- the **loop** (driver) runs on the box next to the worker — it can see session
  files, tmux, git, and react in seconds without an LLM in the judging path;
- the **human's agent** (Hermes) only hears about it through the watchdog's quiet
  relay — so the human gets pinged for: a decision the loop answered, a supervisor
  death, a stale heartbeat, a watchdog self-heal. Never noise while healthy.

## Setup checklist

```bash
# 1. Hermes installed and gateway running (docs: hermes-agent.nousresearch.com/docs)
hermes --version

# 2. install the watchdog script + make it yours
cp watchdog/example-watchdog.sh ~/.hermes/scripts/pi_watchdog.sh
#    edit the unit names / ports / probe conversation to yours

# 3. register it as a no-agent cron (silent when healthy, posts when not)
hermes cron add --schedule "every 30m" --name "pi-chat watchdog" \
  --script pi_watchdog.sh --no-agent --deliver telegram   # or your channel

# 4. driver under systemd user unit (survives logout; linger on)
loginctl enable-linger $USER
systemd-run --user --unit=overnight-driver \
  ~/tt-automatic/driver/overnight-driver.sh "tomorrow 08:00"

# 5. prove both branches BEFORE trusting it overnight:
#    - stop a unit by hand → watchdog tick should report the auto-heal
#    - stop the driver unit → within 30m the heartbeat check must alert
```

## The alert-relay trick (no second scheduler)

The driver never messages the human directly. It writes one file per event:

```
echo "overnight2 decision AUTO-ANSWERED (e/acc-go): <q>" > ~/pi-overnight2-ALERT.txt
```

The watchdog reports the file when it's non-empty AND newer than an `.acked` sibling,
then touches `.acked`. One scheduler, exactly-once delivery, and the human's channel
only ever sees signal.
