#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Code Mode Antigravity MCP server v2 — zero-dependency persistent Python REPL over MCP stdio.

Provides two tools for AI coding agents (Antigravity, Claude Code, Cursor, etc.):
  - py_exec  : execute Python in a named persistent session (thread-safe, multi-session,
               Smart Overflow -> _last_out, built-in helpers: find_files/grep/read_json/tree/state)
  - py_reset : reset one session or all sessions ('*')

Protocol: MCP stdio, JSON-RPC 2.0 (one JSON message per line).
"""
import collections
import json
import os
import re
import subprocess
import sys
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
WORKER_PATH = os.path.join(BASE, "worker.py")
PYTHON = sys.executable
MAX_CHARS = 50000
DEFAULT_MAX_CHARS = 12000
MAX_SESSIONS = 8
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
SERVER_NAME = "code-mode-antigravity"
SERVER_VERSION = "2.0.0"
DEFAULT_PROTOCOL = "2025-06-18"

sys.stdout.reconfigure(encoding="utf-8", newline="\n")
sys.stdin.reconfigure(encoding="utf-8")


def truncate(text, limit=MAX_CHARS):
    if len(text) <= limit:
        return text
    half = limit // 2
    head = text[:half]
    tail = text[-half:]
    head_nl = head.rfind("\n")
    if head_nl > 0:
        head = head[:head_nl]
    tail_nl = tail.find("\n")
    if tail_nl != -1 and tail_nl + 1 < len(tail):
        tail = tail[tail_nl + 1 :]
    omitted = len(text) - len(head) - len(tail)
    return head + "\n... [truncated %d chars] ...\n" % omitted + tail


class Worker:
    """Thread-safe persistent Python subprocess keeping state across py_exec calls."""

    def __init__(self, name="default"):
        self.name = name
        self.proc = None
        self.last_cwd = None
        self.lock = threading.Lock()
        self._stderr_tail = collections.deque(maxlen=30)

    def _alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _drain_stderr(self, pipe):
        try:
            for line in pipe:
                line = line.rstrip("\r\n")
                if line:
                    self._stderr_tail.append(line)
        except (OSError, ValueError):
            pass

    def _format_stderr_tail(self):
        if not self._stderr_tail:
            return ""
        return "\n[worker stderr]\n" + "\n".join(self._stderr_tail)

    def _start_locked(self):
        if self._alive():
            return
        self._stderr_tail.clear()
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        self.proc = subprocess.Popen(
            [PYTHON, "-u", WORKER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self.last_cwd or os.getcwd(),
            env=env,
        )
        threading.Thread(target=self._drain_stderr, args=(self.proc.stderr,), daemon=True).start()

    def _stop_locked(self):
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass

    def stop(self):
        with self.lock:
            self._stop_locked()

    def call(self, code, timeout, cwd=None, max_chars=DEFAULT_MAX_CHARS):
        with self.lock:
            if cwd:
                self.last_cwd = cwd
            self._start_locked()
            try:
                payload = {"code": code, "max_chars": max_chars}
                if cwd:
                    payload["cwd"] = cwd
                self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                tail = self._format_stderr_tail()
                self._stop_locked()
                return {"ok": False, "error": "Failed to send code to Python worker '%s'.%s" % (self.name, tail)}

            box = {}

            def reader():
                try:
                    box["line"] = self.proc.stdout.readline()
                except (OSError, ValueError):
                    box["line"] = ""

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            thread.join(timeout)

            if thread.is_alive():
                self._stop_locked()
                return {
                    "ok": False,
                    "stdout": "",
                    "stderr": "",
                    "error": "Timed out after %ss. Python worker '%s' was stopped; session state was lost."
                    % (timeout, self.name),
                }
            line = box.get("line") or ""
            if not line:
                tail = self._format_stderr_tail()
                self._stop_locked()
                return {"ok": False, "stdout": "", "stderr": "", "error": "Python worker '%s' exited unexpectedly.%s" % (self.name, tail)}
            try:
                return json.loads(line)
            except ValueError:
                tail = self._format_stderr_tail()
                self._stop_locked()
                return {"ok": False, "stdout": "", "stderr": "", "error": "Invalid response from Python worker '%s'.%s" % (self.name, tail)}

    def reset(self):
        self.stop()


WORKERS = {}
WORKERS_LOCK = threading.Lock()
SEND_LOCK = threading.Lock()


def get_worker(session):
    with WORKERS_LOCK:
        worker = WORKERS.get(session)
        if worker is not None:
            return worker, None
        if len(WORKERS) >= MAX_SESSIONS:
            return None, "Too many active sessions (max %d). Reset one with py_reset." % MAX_SESSIONS
        worker = Worker(name=session)
        WORKERS[session] = worker
        return worker, None


def stop_all_workers():
    with WORKERS_LOCK:
        workers = list(WORKERS.values())
        WORKERS.clear()
    for w in workers:
        w.stop()


TOOLS = [
    {
        "name": "py_exec",
        "description": (
            "Run Python code in a PERSISTENT session that keeps variables, imports, and functions "
            "between calls. Built-in helpers: find_files, grep, read_json, tree, state. "
            "Long stdout is saved into _last_out automatically. Supports named parallel sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute."},
                "cwd": {
                    "type": "string",
                    "description": "Working directory (optional; persisted across subsequent calls in the session).",
                },
                "session": {
                    "type": "string",
                    "description": "Optional session name (default 'default') to isolate parallel work.",
                    "default": "default",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Smart Overflow stdout limit (500-50000, default 12000; full output saved in _last_out).",
                    "default": DEFAULT_MAX_CHARS,
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (1-600, default 60).",
                    "default": 60,
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "py_reset",
        "description": (
            "Reset a Python session (clear variables, imports, and functions; keeps last cwd). "
            "Pass session='*' to reset all sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session": {
                    "type": "string",
                    "description": "Session name to reset (default 'default', or '*' for all).",
                    "default": "default",
                },
            },
        },
    },
]


def text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": truncate(text)}], "isError": bool(is_error)}


def _normalize_session(raw):
    if raw is None or raw == "":
        return "default", None
    if not isinstance(raw, str) or not SESSION_RE.match(raw):
        return None, "Invalid session name '%s' (use 1-32 chars: A-Z, a-z, 0-9, _, -)." % raw
    return raw, None


def do_py_exec(args):
    code = args.get("code") or ""
    if not isinstance(code, str) or not code.strip():
        return text_result("Missing required parameter 'code'.", True)
    cwd = args.get("cwd") or None
    if cwd is not None and (not isinstance(cwd, str) or not os.path.isdir(cwd)):
        return text_result("Directory does not exist: %s" % cwd, True)
    session, err = _normalize_session(args.get("session"))
    if err:
        return text_result(err, True)
    try:
        timeout = int(args.get("timeout") or 60)
    except (TypeError, ValueError):
        timeout = 60
    timeout = max(1, min(timeout, 600))
    try:
        max_chars = int(args.get("max_chars") or DEFAULT_MAX_CHARS)
    except (TypeError, ValueError):
        max_chars = DEFAULT_MAX_CHARS
    max_chars = max(500, min(max_chars, MAX_CHARS))

    worker, err = get_worker(session)
    if err:
        return text_result(err, True)

    result = worker.call(code, timeout, cwd, max_chars=max_chars)
    parts = []
    if result.get("stdout"):
        parts.append(result["stdout"].rstrip())
    if result.get("stderr"):
        parts.append("[stderr]\n" + result["stderr"].rstrip())
    if result.get("has_value"):
        parts.append("[value] " + str(result.get("value")))
    if not parts:
        parts.append(result.get("error") or "(no output)")
    elif result.get("error"):
        parts.append(result["error"])
    is_error = not result.get("ok")
    return text_result("\n".join(parts), is_error)


def do_py_reset(args):
    raw = args.get("session")
    if raw == "*":
        stop_all_workers()
        return text_result("All Python sessions reset.")
    session, err = _normalize_session(raw)
    if err:
        return text_result(err, True)
    with WORKERS_LOCK:
        worker = WORKERS.get(session)
    if worker is not None:
        worker.reset()
    return text_result("Python session '%s' reset." % session)


def handle_call(name, args):
    if name == "py_exec":
        return do_py_exec(args)
    if name == "py_reset":
        return do_py_reset(args)
    return text_result("Unknown tool '%s'." % name, True)


def send(message):
    data = json.dumps(message, ensure_ascii=False) + "\n"
    with SEND_LOCK:
        sys.stdout.write(data)
        sys.stdout.flush()


def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion") or DEFAULT_PROTOCOL
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": requested,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Code Mode v2: use py_exec to batch multi-file reads and analysis into one call. "
                    "Built-in helpers: find_files, grep, read_json, tree, state. "
                    "Overflowing stdout is saved in _last_out. Use named sessions for parallel work."
                ),
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        return {"jsonrpc": "2.0", "id": req_id, "result": handle_call(name, args)}
    if method in ("resources/list", "resources/templates/list"):
        return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}
    if method == "logging/setLevel":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "completion/complete":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"completion": {"values": []}}}
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": "Method not found: %s" % method},
    }


def _dispatch(message):
    try:
        response = handle_request(message)
    except Exception as exc:  # pragma: no cover - defensive
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32603, "message": "Internal error: %s" % exc},
        }
    send(response)


def main():
    active_threads = []
    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                continue
            if not isinstance(message, dict) or "method" not in message:
                continue
            if "id" not in message:  # notification
                continue
            # Run tools/call on a worker thread so distinct named sessions execute in parallel.
            if message.get("method") == "tools/call":
                t = threading.Thread(target=_dispatch, args=(message,), daemon=True)
                t.start()
                active_threads = [x for x in active_threads if x.is_alive()]
                active_threads.append(t)
            else:
                _dispatch(message)
        for t in active_threads:
            t.join(timeout=5)
    finally:
        stop_all_workers()


if __name__ == "__main__":
    main()
