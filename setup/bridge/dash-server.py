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


def unit_state(name, bus="user"):
    """Query the correct systemd bus: user units need --user (querying the system
    bus for user units returns 'inactive' — the bug that made the dash lie)."""
    flag = "--user " if bus == "user" else ""
    return run(f"systemctl {flag}is-active {name} 2>/dev/null", 4) or "unknown"


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


def worker_state(now):
    """Deterministic worker state machine: (state, color, detail).
    Truth sources: pi process existence + newest episode session mtime."""
    _, cur = current_episode()
    w = pi_worker()
    age = None
    sub = f"ep counter {current_episode()[0]}"
    if cur:
        age = now - int(os.stat(cur[1]).st_mtime)
        sub = f"E{cur[0]} · {fsize(cur[1])//1024}KB · last write {age}s ago"
    if w:
        sub += f" · pid {w[0]} up {w[1]}"
    if w is None and (age is None or age > 90):
        return ("DEAD (respawn overdue)", "red", sub)
    if w is None:
        return ("BETWEEN (respawning)", "amber", sub)
    if age is None or age < 180:
        return ("WORKING", "green", sub)
    if age < 900:
        return ("THINKING (long API turn)", "amber", sub + " · no writes yet, normal for big turns")
    return ("STALLED (15m+ silent)", "red", sub + " · reaper kills at 30m")


def feed_json(max_events=14, frag=170):
    """Parse the newest episode session tail into events: [{ts, kind, text}]."""
    _, cur = current_episode()
    if not cur:
        return []
    try:
        with open(cur[1], "rb") as f:
            size = os.fstat(f.fileno()).st_size
            f.seek(max(0, size - 49152))
            raw = f.read().decode("utf-8", "replace")
        lines = raw.splitlines()
        if raw and not raw.lstrip().startswith("{") and len(lines) > 1:
            lines = lines[1:]
    except OSError:
        return []
    events = []
    for line in lines[-48:]:
        try:
            d = json.loads(line)
        except Exception:
            continue
        m = d.get("message") or {}
        ts = str(d.get("timestamp") or "")[11:19]
        for p in (m.get("content") or []):
            if not isinstance(p, dict):
                continue
            t = p.get("type")
            if t == "thinking" and (p.get("thinking") or "").strip():
                events.append({"ts": ts, "kind": "thinking", "text": p["thinking"].strip().replace("\n", " ")[:frag]})
            elif t == "text" and (p.get("text") or "").strip():
                events.append({"ts": ts, "kind": "says", "text": p["text"].strip().replace("\n", " ")[:frag]})
            elif t == "toolCall":
                name = p.get("name") or "?"
                a = p.get("arguments") or {}
                c = str(a.get("command"))[:frag] if "command" in a else json.dumps(a, default=str)[:frag]
                events.append({"ts": ts, "kind": "tool", "text": f"{name} {c}"})
    return events[-max_events:]


def activity_feed(max_events=10, frag=170):
    """The 'token streaming' panel: the worker's last thinking / replies / tool
    calls, parsed from the newest episode session tail (~48KB). Newest last."""
    ev = feed_json(max_events, frag)
    out = []
    for e in ev:
        out.append(f"<div class='log'><span class=ts>{html.escape(e['ts'])}</span> [{html.escape(e['kind'])}] {html.escape(e['text'])}</div>")
    return "".join(out) or "<div class='log'>(no activity parsed yet — turn may be mid-API-call)</div>"


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
    drv = unit_state("pi-overnight2-driver.service", "user")
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

    # worker (state machine — proc existence + session-write truth)
    wst, wcolor, wsub = worker_state(now)
    chips.append(chip("pi worker", wst, wcolor, wsub))

    # serve
    sc, tok = serve_health()
    su = unit_state("qwen38-flash-next.service", "system")
    chips.append(chip("Flash-Next serve", "UP" if sc == "200" else sc, "green" if sc == "200" else "red",
                      f"unit {su}{tok}"))

    # convert
    clog_age = file_age(CONVERT_LOG)
    ctail = tail_lines(CONVERT_LOG, 1)
    c_ok = clog_age is not None and clog_age < 300
    chips.append(chip("exl3q convert48", "RUNNING" if c_ok else "STALLED?", "green" if c_ok else "amber",
                      ctail[0][-90:] if ctail else ""))

    # access planes (user units on the user bus; ssh removed 28 Sep)
    for nm, unit, port in (("phone bridge", "pi-chat.service", 7011),
                           ("ttyd tmux", "ttyd-pi-chat.service", 7682)):
        st = unit_state(unit, "user")
        chips.append(chip(nm, st, "green" if st == "active" else "red", f":{port}"))
    tun = unit_state("cloudflared-tunnel.service", "user")
    chips.append(chip("cloudflared tunnel", tun, "green" if tun == "active" else "red", "/dash + model routes"))
    dsh = unit_state("qb2-dash.service", "user")
    chips.append(chip("ops dashboard (this page)", dsh, "green" if dsh == "active" else "red", ":7015"))

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
<meta http-equiv=refresh content=30>
<title>qb2 ops dash</title><style>
body{{background:#0b0f14;color:#d1d5db;font:14px/1.45 ui-monospace,monospace;margin:0;padding:12px}}
h1{{font-size:15px;color:#93c5fd;margin:2px 0 8px}} h2{{font-size:12px;color:#93c5fd;margin:14px 0 4px;text-transform:uppercase;letter-spacing:.05em}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px}}
.chip{{background:#111827;border:1px solid #1f2937;border-radius:8px;padding:8px;display:flex;gap:8px;align-items:flex-start}}
.chip b{{font-size:13px;color:#e5e7eb}} .state{{font-weight:700;font-size:13px}} .sub{{color:#9ca3af;font-size:11px;margin-top:2px}}
.dot{{width:9px;height:9px;border-radius:50%;margin-top:5px;flex-shrink:0}}
.alert{{background:#450a0a;border:1px solid #ef4444;color:#fecaca;padding:8px;border-radius:8px;margin:8px 0}}
.log{{white-space:pre-wrap;border-left:2px solid #1f2937;padding:1px 6px;margin:1px 0;font-size:12px;color:#cbd5e1;word-break:break-all}}
.ts{{color:#64748b;margin-right:6px}} .meta{{color:#64748b;font-size:11px}}</style></head><body>
<h1>qb2 · tt-automatic ops · <span class=meta>refreshed {time.strftime('%H:%M:%S')} UTC · chips 30s · live feed 2.5s</span></h1>
{banner}
<h2>status</h2><div class=grid>{''.join(chips)}</div>
<h2>worker activity (live — thinking / replies / tool calls, updates every 2.5s without reload)</h2><div id=feed>{activity_feed(14)}</div>
<script>
(function(){{
  const feed=document.getElementById('feed');
  const render=j=>j.map(e=>"<div class=log><span class=ts>"+e.ts+"</span> ["+e.kind+"] "+e.text.replace(/&/g,'&amp;').replace(/</g,'&lt;')+"</div>").join('');
  async function poll(){{
    try{{
      const r=await fetch('/dash/feed',{{cache:'no-store'}});
      if(r.ok){{const j=await r.json();const h=render(j);if(h)feed.innerHTML=h;}}
    }}catch(e){{}}
    setTimeout(poll,2500);
  }}
  poll();
}})();
</script>
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
        # 28 Sep user directive: dash is public (no login). Access control happens
        # at the tunnel/LAN layer. Kept as a hook in case auth is ever re-wanted.
        return True

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/dash/feed":
            body = json.dumps(feed_json(14)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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
    print(f"dash on :{PORT} (no auth)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
