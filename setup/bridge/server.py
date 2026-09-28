#!/usr/bin/env python3
"""pi-chat: phone bridge to the pi coding agent.

One long-lived `pi --mode rpc` child per conversation (session-id = conversation id),
so each conversation keeps full context across messages. Stdlib only. Auth at origin:
X-Chat-Key header must match .auth_token — put the bridge behind whatever exposure
layer you trust (LAN-only, tailscale, an authed tunnel path).
"""
import hmac
import json
import os
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(BASE, ".auth_token")).read().strip()
SESSIONS_DIR = os.path.join(BASE, "sessions")
PAGE = open(os.path.join(BASE, "index.html")).read()
PORT = int(os.environ.get("PORT", "7011"))
PI_BIN = "/home/ttuser/.local/bin/pi"
CWD = "/home/ttuser"
PROMPT_TIMEOUT = float(os.environ.get("PROMPT_TIMEOUT", "900"))

children = {}
children_lock = threading.Lock()


def get_child(conv):
    with children_lock:
        c = children.get(conv)
        if c is None or c["proc"].poll() is not None:
            errlog = open(os.path.join(BASE, "state", "pi-stderr.log"), "ab")
            proc = subprocess.Popen(
                [PI_BIN, "--mode", "rpc", "--session-id", conv, "--session-dir", SESSIONS_DIR],
                cwd=CWD,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=errlog,
            )
            c = {"proc": proc, "lock": threading.Lock()}
            children[conv] = c
        return c


def _send(proc, obj):
    proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
    proc.stdin.flush()


def run_prompt(conv, message, timeout=PROMPT_TIMEOUT):
    c = get_child(conv)
    with c["lock"]:
        proc = c["proc"]
        if proc.poll() is not None:
            c2 = get_child(conv)  # respawn dead child
            with children_lock:
                c, proc = c2, c2["proc"]
        rid = "r" + uuid.uuid4().hex[:8]
        _send(proc, {"id": rid, "type": "prompt", "message": message})
        parts, tools = [], []
        deadline = time.time() + timeout
        accepted = False
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                return "(pi rpc child exited — send again to restart)", tools
            try:
                rec = json.loads(line.decode("utf-8", "replace"))
            except Exception:
                continue
            t = rec.get("type")
            if t == "response":
                if rec.get("id") == rid and not rec.get("success"):
                    return "ERROR: " + str(rec.get("error")), tools
                if rec.get("command") == "prompt":
                    accepted = True
            elif t == "message_update":
                ev = rec.get("assistantMessageEvent") or {}
                et = str(ev.get("type"))
                if et == "text_delta":
                    parts.append(ev.get("delta") or "")
                elif "tool" in et:
                    name = ev.get("toolName") or ev.get("name") or ev.get("toolCall", {}).get("name") if isinstance(ev.get("toolCall"), dict) else ev.get("toolName") or ev.get("name")
                    if not name and isinstance(ev.get("toolCall"), dict):
                        name = ev["toolCall"].get("name")
                    args = ev.get("args") or {}
                    try:
                        argstr = json.dumps(args, ensure_ascii=False)[:140]
                    except Exception:
                        argstr = "?"
                    tools.append(f"⚙ {name or 'tool'} {argstr}")
            elif t == "agent_settled":
                break
        else:
            if accepted:
                _send(proc, {"type": "abort"})
                return f"(timed out after {int(timeout)}s — aborted)", tools
        text = "".join(parts).strip()
        return (text or "(empty response)"), tools


def authorized(headers):
    key = headers.get("X-Chat-Key") or ""
    if key.startswith("Bearer "):
        key = key[7:]
    return hmac.compare_digest(key, TOKEN)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in ("/pi-chat", ""):
            b = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)
        elif path == "/pi-chat/api/health":
            self._json(200 if authorized(self.headers) else 401,
                       {"ok": True, "conversations": len(children), "time": time.time()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if path != "/pi-chat/api/send":
            self._json(404, {"error": "not found"})
            return
        if not authorized(self.headers):
            self._json(401, {"error": "bad key"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            conv = str(body.get("conv") or "")[:64]
            message = str(body.get("message") or "")
            assert conv and message.strip()
        except Exception:
            self._json(400, {"error": "need JSON {conv, message}"})
            return
        if not all(ch in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in conv):
            self._json(400, {"error": "bad conv id"})
            return
        try:
            text, tools = run_prompt(conv, message)
            self._json(200, {"text": text, "tools": tools})
        except Exception as e:
            self._json(500, {"error": str(e)})


if __name__ == "__main__":
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    os.makedirs(os.path.join(BASE, "state"), exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"pi-chat on :{PORT} (auth on, {PROMPT_TIMEOUT}s prompt timeout)", flush=True)
    srv.serve_forever()
