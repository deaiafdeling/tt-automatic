#!/bin/bash
# Pane wrapper for overnight2 turns: runs the continue script, tees output to
TTA_HOME="${TTA_HOME:-$HOME}"   # root of your work tree; scripts below are relative to it
# the log, records the turn's exit code. Lives entirely in bash — the tmux
# pane just execs this file (no inline quoting ambiguity).
export PATH="${TTA_HOME}/.local/bin:$PATH"
source ${TTA_HOME}/tt-qwen-3.8-flash-next/python_env/bin/activate
cd ${TTA_HOME}/tt-qwen-3.8-flash-next
bash ${TTA_HOME}/pi-overnight2-continue.sh 2>&1 | tee -a ${TTA_HOME}/pi-overnight2.log
ec=${PIPESTATUS[0]}
echo "[turn exited $(date +%H:%M:%S) ec=$ec]"
sleep 3600
