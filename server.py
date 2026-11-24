#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Code Mode Antigravity MCP server — zero-dependency persistent Python REPL over MCP stdio.

Provides two tools for AI coding agents (Antigravity, Claude Code, Cursor, etc.):
  - py_exec  : execute Python in a live subprocess, keeping variables and imports
  - py_reset : reset the live Python session

Protocol: MCP stdio, JSON-RPC 2.0 (one JSON message per line).
"""
import json
import os
import subprocess
import sys
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
WORKER_PATH = os.path.join(BASE, "worker.py")
PYTHON = sys.executable
MAX_CHARS = 50000
SERVER_NAME = "code-mode-antigravity"
SERVER_VERSION = "1.0.0"
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
    """Persistent Python subprocess keeping state across py_exec calls."""

    def __init__(self):
        self.proc = None
        self.last_cwd = None

    def _alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self._alive():
            return
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        self.proc = subprocess.Popen(
            [PYTHON, "-u", WORKER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self.last_cwd or os.getcwd(),
            env=env,
        )

    def stop(self):
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
        for pipe in (proc.stdin, proc.stdout):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass

    def call(self, code, timeout, cwd=None):
        if cwd:
            self.last_cwd = cwd
        self.start()
        try:
            payload = {"code": code}
            if cwd:
                payload["cwd"] = cwd
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self.stop()
            return {"ok": False, "error": "Failed to send code to the Python worker."}

        box = {}

        def reader():
            box["line"] = self.proc.stdout.readline()

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            self.stop()
            return {
                "ok": False,
                "stdout": "",
                "stderr": "",
                "error": "Timed out after %ss. Python worker was stopped; session state was lost." % timeout,
            }
        line = box.get("line") or ""
        if not line:
            self.stop()
            return {"ok": False, "stdout": "", "stderr": "", "error": "Python worker exited unexpectedly."}
        try:
            return json.loads(line)
        except ValueError:
            self.stop()
            return {"ok": False, "stdout": "", "stderr": "", "error": "Invalid response from Python worker."}

    def reset(self):
        self.stop()


WORKER = Worker()

TOOLS = [
    {
        "name": "py_exec",
        "description": (
            "Run Python code in a PERSISTENT session that keeps variables, imports, and functions "
            "between calls. Use it to batch multi-file reads, data filtering, calculations, or "
            "repetitive checks into one tool call. Returns stdout, stderr, and the final expression value."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute."},
                "cwd": {
                    "type": "string",
                    "description": "Working directory (optional; persisted across subsequent calls in the session).",
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
            "Reset the Python session: clear all variables, imports, and defined functions "
            "(keeps the last working directory)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": truncate(text)}], "isError": bool(is_error)}


def do_py_exec(args):
    code = args.get("code") or ""
    if not isinstance(code, str) or not code.strip():
        return text_result("Missing required parameter 'code'.", True)
    cwd = args.get("cwd") or None
    if cwd is not None and (not isinstance(cwd, str) or not os.path.isdir(cwd)):
        return text_result("Directory does not exist: %s" % cwd, True)
    try:
        timeout = int(args.get("timeout") or 60)
    except (TypeError, ValueError):
        timeout = 60
    timeout = max(1, min(timeout, 600))

    result = WORKER.call(code, timeout, cwd)
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


def handle_call(name, args):
    if name == "py_exec":
        return do_py_exec(args)
    if name == "py_reset":
        WORKER.reset()
        return text_result("Python session reset.")
    return text_result("Unknown tool '%s'." % name, True)


def send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
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
                    "Code Mode: use py_exec to batch multiple operations into a single call; "
                    "Python variables and imports persist across calls."
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


def main():
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
            try:
                response = handle_request(message)
            except Exception as exc:  # pragma: no cover - defensive
                response = {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "error": {"code": -32603, "message": "Internal error: %s" % exc},
                }
            send(response)
    finally:
        WORKER.stop()


if __name__ == "__main__":
    main()
