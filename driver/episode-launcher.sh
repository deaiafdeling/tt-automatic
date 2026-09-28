#!/bin/bash
# Episodic turn launcher (Ralph/nightcrawler pattern): each turn is a FRESH pi
# context; all state lives on disk (GOAL_BRIEF.md + KANBAN.md + git). Boots fast,
# no context replay growth. Injects the driver's auto-answer when one is pending.
export PATH="/home/ttuser/.local/bin:$PATH"
source /home/ttuser/tt-qwen-3.8-flash-next/python_env/bin/activate
cd /home/ttuser/tt-qwen-3.8-flash-next
EP=$(cat /home/ttuser/pi-overnight2-EP 2>/dev/null || echo 1)
ANSWER=/home/ttuser/pi-overnight2-ANSWER.txt
REORIENT=/home/ttuser/pi-overnight2-REORIENT
P="You are turn $EP of the overnight loop on the QuietBox Flash-Next speed mission. This episode is a FRESH context — all state lives on disk, so re-orient from files before anything else:
1. cat ~/tt-contrib/GOAL_BRIEF.md  (the contract: objective, constraints, validation, stop conditions)
2. tail -n 40 ~/tt-contrib/KANBAN.md  (landed work; the last lines are the live handoff — start from the newest NEXT)
3. git -C ~/tt-qwen-3.8-flash-next log --oneline -8
4. Preflight: serve UP (systemctl is-active qwen38-flash-next + :8000/health), exl3q convert PID 57024 alive and owns CPU, mesh ownership via fuser.
5. Experiment ledger: ~/tt-contrib/analysis/experiments.tsv (commit | area | metric | value | unit | status keep/discard/crash/published | run_id | description). Every benchmarked A/B gets a row — keep/discard per the comparison rule, published rows cite the run id. Never redefine a metric or compare across profiles; same-config re-runs that confirm a number also get a row.
Then pick the highest-value next step on the active ticket (GOAL_BRIEF T22-T26 priority, latest KANBAN NEXT) and do ONE focused unit of work: implement, validate with the narrowest test suite, bench if serve-affecting (mesh windows only via the tt-mesh-window ladder; serve back UP before the turn ends), commit + KANBAN line.
End-of-turn contract (mandatory): append a KANBAN line 'turn-$EP: <landed> — NEXT: <what>' so the next episode can pick up cold; leave the serve UP; if a decision truly needs the user, reply with exactly 'USER_DECISION_NEEDED: <question>' and stop; if the window elapsed, write the final summary to KANBAN and reply exactly 'OVERNIGHT_WINDOW_COMPLETE'."
if [ -f "$REORIENT" ]; then
  P="ESCALATED RE-ORIENT (previous episodes were judged unproductive — do NOT continue the same approach blind): spend this episode primarily re-reading state (GOAL_BRIEF, full KANBAN tail, git log, BRINGUP.md relevant section), identify why recent episodes stalled, then either fix that root cause or pick a DIFFERENT high-value ticket. One focused unit of work still required.

$P"
  rm -f "$REORIENT"
fi
if [ -f "$ANSWER" ]; then
  P="The operator auto-answered your pending question (standing e/acc-go policy):

$(cat "$ANSWER")

$P"
  rm -f "$ANSWER"
fi
exec /home/ttuser/.local/bin/pi --session-id "T24-overnight2-E$EP" \
  --append-system-prompt /home/ttuser/.pi/agent/APPEND_SYSTEM.md \
  -p "$P" 2>> /home/ttuser/pi-overnight2-pi-stderr.log
