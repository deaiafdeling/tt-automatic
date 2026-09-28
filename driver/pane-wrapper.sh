#!/bin/bash
# Pane wrapper for overnight2 turns: runs the continue script, tees output to
# the log, records the turn's exit code. Lives entirely in bash — the tmux
# pane just execs this file (no inline quoting ambiguity).
export PATH="/home/ttuser/.local/bin:$PATH"
source /home/ttuser/tt-qwen-3.8-flash-next/python_env/bin/activate
cd /home/ttuser/tt-qwen-3.8-flash-next
bash /home/ttuser/pi-overnight2-continue.sh 2>&1 | tee -a /home/ttuser/pi-overnight2.log
ec=${PIPESTATUS[0]}
echo "[turn exited $(date +%H:%M:%S) ec=$ec]" >> /home/ttuser/pi-overnight2.log
echo "[turn exited $(date +%H:%M:%S) ec=$ec]"
sleep 3600
