#!/usr/bin/env python3
"""tt-automatic ops dashboard: one glance — is pi working?

Deterministic only: systemd unit states, process checks, session-file mtimes,
git logs, board + ledger tails, serve health. No LLM, no heuristics — every number
comes from a file or a subprocess on this box. Read-only (GET only).

Auth: HTTP Basic, same credential file as the ttyd bridges (.ttyd_cred).
Port 7015; systemd user unit; meta-refresh 15s.
"""
import base64
import glob
import hmac
import html
import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
PORT = int(os.environ.get("DASH_PORT", "7015"))
Q_TREE = os.path.join(HOME, "tt-qwen-3.8-flash-next")
C_TREE = os.path.join(HOME, "tt-contrib")
SESS_DIR = os.environ.get("DASH_SESS_DIR", os.path.join(HOME, ".pi/agent/sessions/--home-ttuser-tt-qwen-3.8-flash-next--"))
EPFILE = os.path.join(HOME, "pi-overnight2-EP")
ALERT = os.path.join(HOME, "pi-overnight2-ALERT.txt")
HEART = os.path.join(HOME, "pi-overnight2-driver.heartbeat")
WIN_FLAG = os.path.join(HOME, "pi-overnight2-WINDOW_LIVE")
LEDGER = os.path.join(C_TREE, "analysis/experiments.tsv")
CONVERT_LOG = os.path.join(C_TREE, "exl3q/_convert48.log")
PI_STDERR = os.path.join(HOME, "pi-overnight2-pi-stderr.log")
CRED = os.path.join(HOME, "pi-chat/.ttyd_cred")
CONVERT_PID = os.environ.get("DASH_CONVERT_PID", "57024")


def run(cmd, timeout=6):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return f"(err: {e})"


def unit_state(name):
    return run(f"systemctl is-active {name} 2>/dev/null", 4) or "unknown"


def file_age(path):
    try:
        return int(time.time() - os.stat(path).st_mtime)
    except OSError:
        return None


def fsize(path):
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def tail_lines(path, n, width=200):
    try:
        with open(path, errors="replace") as f:
            lines = f.read().splitlines()[-n:]
        return [l[-width:] for l in lines]
    except OSError:
        return []


def pi_worker():
    """Return (pid, etime) of the current loop pi process, or None."""
    out = run("ps -eo pid,etime,args", 4)
    for line in out.splitlines():
        if ".local/bin/pi" in line and "T24-overnight2-E" in line:
            parts = line.split()
            return parts[0], parts[1]
    return None


def current_episode():
    try:
        ep = int(open(EPFILE).read().strip())
    except Exception:
        ep = 0
    best = None
    for f in glob.glob(os.path.join(SESS_DIR, "*_T24-overnight2-E*.jsonl")):
        try:
            m = int(f.rsplit("E", 1)[1].split(".")[0])
            if best is None or m > best[0]:
                best = (m, f)
        except ValueError:
            continue
    return ep, best


def serve_health():
    code = run("curl -s --max-time 4 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health", 6)
    tok = ""
    if code == "200":
        h = run("curl -s --max-time 4 http://127.0.0.1:8000/health", 6)
        try:
            d = json.loads(h)
            for k in ("tok_s", "tokens_per_second", "tokSOut"):
                if k in d:
                    tok = f" · {d[k]} tok/s"
                    break
        except Exception:
            pass
    return code, tok


def chip(label, state, color, sub=""):
    cls = {"green": "#22c55e", "amber": "#f59e0b", "red": "#ef4444", "gray": "#64748b"}[color]
    sub_h = f"<div class='sub'>{html.escape(sub)}</div>" if sub else ""
    return (f"<div class='chip'><div class='dot' style='background:{cls}'></div>"
            f"<div><b>{html.escape(label)}</b><div class='state' style='color:{cls}'>{html.escape(state)}</div>{sub_h}</div></div>")


def logdiv(lines):
    return "".join(f"<div class='log'>{html.escape(l)}</div>" for l in lines)


def build_page():
    now = int(time.time())
    ep, cur = current_episode()
    chips = []
    banner = ""

    # driver (shift boss)
    drv = unit_state("pi-overnight2-driver.service")
    hage = file_age(HEART)
    window = os.path.exists(WIN_FLAG)
    drv_color = "green" if drv == "active" and hage is not None and hage < 300 else ("amber" if drv == "active" else "red")
    win_left = ""
    try:
        with open(os.path.join(BASE, "window_end")) as f:
            left = int(open(os.path.join(BASE, "window_end")).read().strip()) - now
        win_left = f"{left//3600}h{(left % 3600)//60:02d}m left" if left > 0 else "window over"
    except Exception:
        win_left = "window: n/a"
    chips.append(chip("driver (shift boss)", drv, drv_color,
                      f"heartbeat {hage}s ago · {win_left}" if hage is not None else win_left))
    if window and hage is not None and hage > 3600:
        banner = "<div class='alert'>⚠ window flag live but driver heartbeat stale — supervisor may be dead</div>"

    # worker
    w = pi_worker()
    if cur:
        age = now - int(os.stat(cur[1]).st_mtime)
        sz = fsize(cur[1])
        state, color = ("WORKING", "green") if age < 180 else (("QUIET", "amber") if age < 600 else ("STALLED", "red"))
        sub = f"E{cur[0]} · {sz//1024}KB · last write {age}s ago"
        if w:
            sub += f" · pid {w[0]} up {w[1]}"
        chips.append(chip("pi worker", state, color, sub))
    else:
        chips.append(chip("pi worker", "NO SESSION", "red", f"ep counter {ep}"))

    # serve
    sc, tok = serve_health()
    su = unit_state("qwen38-flash-next.service")
    chips.append(chip("Flash-Next serve", "UP" if sc == "200" else sc, "green" if sc == "200" else "red",
                      f"unit {su}{tok}"))

    # convert
    clog_age = file_age(CONVERT_LOG)
    ctail = tail_lines(CONVERT_LOG, 1)
    c_ok = clog_age is not None and clog_age < 300
    chips.append(chip("exl3q convert48", "RUNNING" if c_ok else "STALLED?", "green" if c_ok else "amber",
                      ctail[0][-90:] if ctail else ""))

    # access planes
    for nm, unit, port in (("phone bridge", "pi-chat.service", 7011),
                           ("ttyd tmux", "ttyd-pi-chat.service", 7682),
                           ("ttyd ssh", "ttyd-ssh.service", 7683)):
        st = unit_state(unit)
        chips.append(chip(nm, st, "green" if st == "active" else "red", f":{port}"))
    tun = unit_state("cloudflared-tunnel.service")
    chips.append(chip("cloudflared tunnel", tun, "green" if tun == "active" else "red"))

    # active driver alert (fresh <2h)
    aage = file_age(ALERT)
    if aage is not None and aage < 7200 and fsize(ALERT) > 0:
        try:
            banner += f"<div class='alert'>⚠ DRIVER ALERT ({aage}s old): {html.escape(open(ALERT, errors='replace').read()[:300])}</div>"
        except OSError:
            pass

    # driver log tail
    drvlog = tail_lines(os.path.join(HOME, "pi-overnight2-driver.log"), 14)

    # git tails
    gq = run(f"git -C {Q_TREE} log --oneline -6", 5).splitlines()
    gc = run(f"git -C {C_TREE} log --oneline -5", 5).splitlines()
    git_html = logdiv([f"q {l}" for l in gq] + [f"c {l}" for l in gc])

    # ledger tail
    led_html = logdiv(tail_lines(LEDGER, 8, width=300))

    # board tail
    board_html = logdiv(tail_lines(os.path.join(C_TREE, "KANBAN.md"), 24, width=400))

    # pi stderr tail
    perr = tail_lines(PI_STDERR, 6, width=160) if fsize(PI_STDERR) else []
    perr_html = logdiv(perr) if perr else "<div class='log'>(empty — no stderr from pi this session)</div>"

    # system line
    load = ", ".join(f"{x:.1f}" for x in os.getloadavg())
    mem = run("free -g | awk 'NR==2{print $3\"G used / \"$2\"G\"}'", 4)
    conv_up = run(f"ps -o etime= -p {CONVERT_PID} 2>/dev/null | tr -d ' '", 4) or "-"

    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<meta http-equiv=refresh content=15>
<title>qb2 ops dash</title><style>
body{{background:#0b0f14;color:#d1d5db;font:14px/1.45 ui-monospace,monospace;margin:0;padding:12px}}
h1{{font-size:15px;color:#93c5fd;margin:2px 0 8px}} h2{{font-size:12px;color:#93c5fd;margin:14px 0 4px;text-transform:uppercase;letter-spacing:.05em}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px}}
.chip{{background:#111827;border:1px solid #1f2937;border-radius:8px;padding:8px;display:flex;gap:8px;align-items:flex-start}}
.chip b{{font-size:13px;color:#e5e7eb}} .state{{font-weight:700;font-size:13px}} .sub{{color:#9ca3af;font-size:11px;margin-top:2px}}
.dot{{width:9px;height:9px;border-radius:50%;margin-top:5px;flex-shrink:0}}
.alert{{background:#450a0a;border:1px solid #ef4444;color:#fecaca;padding:8px;border-radius:8px;margin:8px 0}}
.log{{white-space:pre-wrap;border-left:2px solid #1f2937;padding:1px 6px;margin:1px 0;font-size:12px;color:#cbd5e1;word-break:break-all}}
.meta{{color:#64748b;font-size:11px}}</style></head><body>
<h1>qb2 · tt-automatic ops · <span class=meta>refreshed {time.strftime('%H:%M:%S')} UTC · auto-refresh 15s</span></h1>
{banner}
<h2>status</h2><div class=grid>{''.join(chips)}</div>
<h2>driver log</h2>{logdiv(drvlog)}
<h2>git (q = worker tree · c = contrib)</h2>{git_html}
<h2>experiment ledger (tail)</h2>{led_html}
<h2>KANBAN tail (live handoff)</h2>{board_html}
<h2>pi stderr</h2>{perr_html}
<div class=meta>load {load} · mem {mem} · convert uptime {conv_up}</div>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _authed(self):
        try:
            cred = open(CRED, "rb").read().strip()
        except OSError:
            return False
        h = self.headers.get("Authorization") or ""
        if not h.startswith("Basic "):
            return False
        try:
            supplied = base64.b64decode(h[6:]).strip()
        except Exception:
            return False
        return hmac.compare_digest(supplied, cred)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path not in ("/dash", "/dash/"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._authed():
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Basic realm=qb2")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        page = build_page().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


if __name__ == "__main__":
    print(f"dash on :{PORT} (basic auth)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
