#!/bin/bash
# Auto-continue driver v2 for the overnight pi loop — EPISODIC (Ralph/nightcrawler
TTA_HOME="${TTA_HOME:-$HOME}"   # root of your work tree; scripts below are relative to it
# pattern): fresh pi context per turn, all state on disk (GOAL_BRIEF + KANBAN + git).
# Judges each finished turn; on unproductive episodes ESCALATES (re-orient episode)
# instead of halting; halts only on repeated ignored decisions, rebuild exhaustion,
# or window end. Alert relay: ~/pi-overnight2-ALERT.txt via pi_watchdog §5.
# Heartbeat: ~/pi-overnight2-driver.heartbeat (watchdog §6 alert if stale).
set -u
Q_TREE=${TTA_HOME}/tt-qwen-3.8-flash-next
C_TREE=${TTA_HOME}/tt-contrib
SESS_GLOB="${TTA_HOME}/.pi/agent/sessions/*/*_T24-overnight2-E*.jsonl"
STATE=${TTA_HOME}/pi-overnight2-driver.state
ALERT=${TTA_HOME}/pi-overnight2-ALERT.txt
LOG=${TTA_HOME}/pi-overnight2-driver.log
HEART=${TTA_HOME}/pi-overnight2-driver.heartbeat
WIN_FLAG=${TTA_HOME}/pi-overnight2-WINDOW_LIVE
EPFILE=${TTA_HOME}/pi-overnight2-EP
WIN_END=$(date -d "${1:-2026-09-28 14:55:00 UTC}" +%s)
TMUX_WIN=pi-chat:overnight2
say(){ echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }
alert(){ echo -e "$1" > "$ALERT"; say "ALERT: $1"; }
sess_file(){ ls -t $SESS_GLOB 2>/dev/null | head -1; }
last_text(){  # last assistant text part in the session (first lines of it)
  python3 - "$1" << 'PYEOF'
import json, sys
last=""
with open(sys.argv[1]) as f:
    for line in f:
        try: d=json.loads(line)
        except Exception: continue
        m=d.get('message') or {}
        if m.get('role')=='assistant':
            for c in (m.get('content') or []):
                if isinstance(c,dict) and c.get('type')=='text' and c.get('text','').strip():
                    last=c['text'].strip()
print('\n'.join(last.splitlines()[:6]) if last else '(no assistant text yet)')
PYEOF
}
answer_decision(){  # compose the e/acc-go answer for question $1
  cat << EOF2
DECISION (auto-answered under the operator's standing e/acc-go policy):
Question you asked: $1
Answer: proceed NOW with the most aggressive forward option that does NOT break
known-good (rollback tags checkpoint-20260926-serve-good and checkpoint-20260927-arm2-win,
the published record config, acceptance refs). Bench immediately after the change;
publish only wins; commit + KANBAN every increment. If every forward option breaks
known-good, take the protective option, log the decision in KANBAN, and move to the
next-highest-value ticket. Do not ask again — decide, log, continue.
EOF2
}

say "driver v2 started (window ends $(date -d "@$WIN_END" '+%H:%M %Z'), episodic)"
touch "$WIN_FLAG" "$HEART"
CC0=$(git -C "$Q_TREE" rev-list --count HEAD 2>/dev/null || echo 0)
KB0=$(md5sum "$C_TREE/KANBAN.md" 2>/dev/null | cut -d' ' -f1)
echo "$CC0" > "$STATE"; echo "$KB0" > "$STATE".kb
echo 0 > "$STATE".size
echo 0 > "$STATE".weak; : > "$STATE".hash; echo 0 > "$STATE".dec
echo 0 > "$STATE".rebuilds
echo 1 > "$STATE".skip          # first judgment may be a boot-race turn
[ -f "$EPFILE" ] || echo 9 > "$EPFILE"   # turn-8 (old scheme) was running when v2 deployed

REBUILD_MAX=6    # hard ceiling of escalated episodes per window
while :; do
  sleep 20
  touch "$HEART"
  PIDS=$(pgrep -f 'pi --session-id T24-overnight2' | sort -n | tr '\n' ' ')
  SF=$(sess_file)
  # stall watchdog: no session write 30 min while a turn runs => hung turn
  # (pi issue #8331 class: stalled provider stream never ends the turn)
  if [ -n "$PIDS" ] && [ -n "$SF" ]; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$SF") ))
    if [ "$AGE" -gt 1800 ]; then
      say "STALL: no session write ${AGE}s — killing turn pid(s): $PIDS"
      pkill -f 'pi --session-id T24-overnight2'; sleep 5
      echo 1 > "$STATE.skip"; WEAK=$(cat "$STATE".weak); echo $((WEAK+1)) > "$STATE".weak
    fi
  fi
  pgrep -f 'pi --session-id T24-overnight2' >/dev/null && continue   # turn still running

  # ---- turn ended: judge quality before continuing ----
  NOW=$(date +%s)
  if [ "$NOW" -ge "$WIN_END" ]; then
    alert "overnight2: window elapsed ($(date -d "@$NOW" '+%H:%M %Z')). Driver stopping. Verify serve UP on next check."
    rm -f "$WIN_FLAG"; break
  fi
  SF=$(sess_file)
  TXT=$( [ -n "$SF" ] && last_text "$SF" || echo '(no session)')
  CC1=$(git -C "$Q_TREE" rev-list --count HEAD 2>/dev/null || cat "$STATE")
  KB1=$(md5sum "$C_TREE/KANBAN.md" 2>/dev/null | cut -d' ' -f1)
  LG1=$(md5sum "$C_TREE/analysis/experiments.tsv" 2>/dev/null | cut -d' ' -f1)
  SZ1=$( [ -n "$SF" ] && stat -c %s "$SF" || echo 0)
  CC0=$(cat "$STATE"); KB0=$(cat "$STATE".kb); LG0=$(cat "$STATE".lg 2>/dev/null || echo x); SZ0=$(cat "$STATE".size)
  GOT_COMMIT=0; [ "$CC1" != "$CC0" ] && GOT_COMMIT=1
  GOT_KANBAN=0; [ "$KB1" != "$KB0" ] && GOT_KANBAN=1
  DELTA=$((SZ1 - SZ0)); [ "$DELTA" -lt 0 ] && DELTA=0
  [ "$GOT_COMMIT" = 1 ] || [ "$GOT_KANBAN" = 1 ] && echo 0 > "$STATE".dec
  case "$TXT" in
    *USER_DECISION_NEEDED*)
      Q="$(printf '%s' "${TXT#*USER_DECISION_NEEDED: }" | head -n 2 | tr '\n' ' ')"
      N=$(( $(cat "$STATE.dec") + 1 )); echo $N > "$STATE.dec"
      if [ "$N" -ge 3 ]; then
        alert "overnight2 asked the same decision class 3x without progressing — halting for the user: $Q"
        rm -f "$WIN_FLAG"; break
      fi
      answer_decision "$Q" > ${TTA_HOME}/pi-overnight2-ANSWER.txt
      alert "overnight2 decision AUTO-ANSWERED (e/acc-go, ask#$N): $Q"
      ;;&  # fall through to the weak/respawn logic below
    *OVERNIGHT_WINDOW_COMPLETE*)
      alert "overnight2 reports OVERNIGHT_WINDOW_COMPLETE. Driver stopping."
      rm -f "$WIN_FLAG"; break;;
  esac
  H=$(printf '%s' "$TXT" | head -c 200 | md5sum | cut -d' ' -f1)
  PH=$(cat "$STATE".hash); WEAK=$(cat "$STATE".weak)
  if [ -s "$STATE.skip" ]; then
    # boot-race turn: its bytes/text belong to startup, not work quality
    WEAK=0; rm -f "$STATE.skip"; say "boot turn — quality judgment skipped"
  elif [ "$H" = "$PH" ]; then WEAK=$((WEAK+1)); say "weak++ (identical last text)"
  elif [ "$GOT_COMMIT" = 0 ] && [ "$GOT_KANBAN" = 0 ] && [ "$GOT_LEDGER" = 0 ] && [ "$DELTA" -lt 2000 ]; then
    WEAK=$((WEAK+1)); say "weak++ (no commit/kanban, tiny turn Δ${DELTA}B)"
  else
    WEAK=0; echo 0 > "$STATE".rebuilds
  fi
  echo "$H" > "$STATE".hash; echo $WEAK > "$STATE".weak
  echo "$CC1" > "$STATE"; echo "$KB1" > "$STATE".kb; echo "$LG1" > "$STATE".lg; echo "$SZ1" > "$STATE".size
  if [ "$WEAK" -ge 3 ]; then
    REB=$(cat "$STATE".rebuilds)
    if [ "$REB" -ge "$REBUILD_MAX" ]; then
      alert "overnight2: $REB escalated episodes still unproductive — halting for the user. Last text: ${TXT:0:200}"
      rm -f "$WIN_FLAG"; break
    fi
    echo $((REB+1)) > "$STATE".rebuilds
    echo 0 > "$STATE".weak
    EP=$(cat "$EPFILE"); echo $((EP+1)) > "$EPFILE"
    touch ${TTA_HOME}/pi-overnight2-REORIENT
    alert "overnight2: 3 unproductive episodes — ESCALATING to re-orient episode E$((EP+1)) (rebuild $((REB+1))/$REBUILD_MAX), not halting."
  fi
  say "turn judged: commit=$GOT_COMMIT kanban=$GOT_KANBAN Δ=${DELTA}B weak=$WEAK ep=$(cat "$EPFILE") rebuilds=$(cat "$STATE".rebuilds) — continuing"
  EP=$(cat "$EPFILE"); echo $((EP+1)) > "$EPFILE"   # next episode id
  RESPAWN="bash ${TTA_HOME}/pi-overnight2-pane.sh"
  if ! tmux list-windows -t pi-chat -F '#{window_name}' 2>/dev/null | grep -qx overnight2; then
    tmux new-window -t pi-chat -n overnight2 "$RESPAWN" \; 2>>"$LOG"
  else
    tmux respawn-pane -k -t "$TMUX_WIN" "$RESPAWN" \; 2>>"$LOG"
  fi
  # post-respawn: wait for pi boot before probing (episodic boots are fast, but be safe)
  B=0
  while [ $B -lt 24 ]; do
    sleep 5; B=$((B+1))
    pgrep -f 'pi --session-id T24-overnight2' >/dev/null && break
  done
  if ! pgrep -f 'pi --session-id T24-overnight2' >/dev/null; then
    sleep 30
    pgrep -f 'pi --session-id T24-overnight2' >/dev/null || alert "overnight2: respawn produced no pi process — check ~/pi-overnight2.log"
  else
    sleep 20   # let the session file settle, then baseline size for honest deltas
    sess_file | xargs -r stat -c %s > "$STATE".size
    echo 1 > "$STATE".skip
  fi
done
say "driver v2 exiting"
rm -f "$WIN_FLAG"
