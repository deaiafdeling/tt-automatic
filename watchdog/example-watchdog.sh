#!/bin/bash
# pi-chat watchdog: keeps the pi agent chain (bridge + ttyd + tmux access) up.
# Silent (exit 0, no output) when healthy — cron no_agent mode sends nothing.
# Outputs a failure report only when something is actually broken.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
PI=${TTA_HOME}/pi-chat
TOKEN=$(cat "$PI/.auth_token" 2>/dev/null)
failed=0
msgs=()

# 1. systemd user units — self-heal: start inactive ones, re-check after 6s
for u in pi-chat.service ttyd-pi-chat.service ttyd-ssh.service; do
  st=$(systemctl --user is-active "$u" 2>/dev/null)
  if [ "$st" != "active" ]; then
    systemctl --user start "$u" >/dev/null 2>&1
    sleep 6
    st=$(systemctl --user is-active "$u" 2>/dev/null)
    if [ "$st" != "active" ]; then
      failed=1
      msgs+=("$u NOT active even after restart attempt (state: ${st:-missing})")
    else
      msgs+=("$u was down — auto-restarted OK")
    fi
  fi
done

# 2. ports actually listening
for p in 7011 7682 7683; do
  if ! ss -tln 2>/dev/null | grep -q ":$p "; then
    failed=1
    msgs+=("port $p not listening")
  fi
done

# 3. bridge health endpoint (authed)
h=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
    -H "X-Chat-Key: $TOKEN" http://127.0.0.1:7011/pi-chat/api/health 2>/dev/null)
if [ "$h" != "200" ]; then
  failed=1
  msgs+=("bridge /pi-chat/api/health returned '$h' (want 200)")
fi

# 4. deep probe: full round-trip bridge -> pi child -> LLM provider
if [ "$failed" -eq 0 ]; then
  probe() {
    curl -s --max-time 300 -X POST \
      -H "X-Chat-Key: $TOKEN" -H 'Content-Type: application/json' \
      -d '{"conv":"watchdog-probe","message":"Health probe: reply with exactly PI-ALIVE and nothing else."}' \
      http://127.0.0.1:7011/pi-chat/api/send 2>/dev/null
  }
  resp=$(probe)
  if ! printf '%s' "$resp" | grep -q 'PI-ALIVE'; then
    # self-heal: kill the wedged watchdog pi child; bridge respawns it on next send
    pkill -f 'session-id watchdog-probe' 2>/dev/null
    sleep 5
    resp=$(probe)
    if printf '%s' "$resp" | grep -q 'PI-ALIVE'; then
      msgs+=("deep probe failed once (wedged pi child killed, respawn OK)")
    else
      failed=1
      msgs+=("deep probe FAILED twice: pi agent did not return PI-ALIVE")
      [ -n "$resp" ] && msgs+=("probe response: $(printf '%s' "$resp" | head -c 400)")
      msgs+=("(empty/timeout => pi child or LLM provider hung; see ~/pi-chat/state/pi-stderr.log)")
    fi
  fi
fi

# 5. overnight pi-loop driver alert relay (fresh alert reported once, then acked)
DRIVER_ALERT=${TTA_HOME}/pi-overnight2-ALERT.txt
if [ -s "$DRIVER_ALERT" ] && [ "$DRIVER_ALERT" -nt "$DRIVER_ALERT.acked" ]; then
  msgs+=("OVERNIGHT DRIVER: $(head -c 350 "$DRIVER_ALERT" | tr '\n' ' ')")
  touch "$DRIVER_ALERT.acked"
fi

# 6. overnight loop liveness (only while the driver declares a live window)
WIN_FLAG=${TTA_HOME}/pi-overnight2-WINDOW_LIVE
HEART=${TTA_HOME}/pi-overnight2-driver.heartbeat
if [ -f "$WIN_FLAG" ]; then
  HAGE=$(( $(date +%s) - $(stat -c %Y "$HEART" 2>/dev/null || echo 0) ))
  if [ "$HAGE" -gt 3600 ]; then
    failed=1
    msgs+=("overnight driver heartbeat stale ${HAGE}s while window flag live — loop dead? (restart: systemd-run --user --unit=pi-overnight2-driver ${TTA_HOME}/pi-overnight2-driver.sh)")
  fi
fi

if [ "$failed" -eq 1 ]; then
  echo "PI-CHAT WATCHDOG: PROBLEMS DETECTED"
  for m in "${msgs[@]}"; do echo "- $m"; done
elif [ "${#msgs[@]}" -gt 0 ]; then
  # healed this tick — worth one quiet notice, then silence again
  echo "PI-CHAT WATCHDOG: auto-healed this tick:"
  for m in "${msgs[@]}"; do echo "- $m"; done
fi
exit 0
