#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke test for server.py over MCP stdio JSON-RPC."""
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(BASE, "server.py")


def main():
    proc = subprocess.Popen(
        [sys.executable, "-u", SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    def rpc(req_id, method, params=None):
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("Server did not respond: %s" % proc.stderr.read())
        return json.loads(line)

    init = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}})
    print("initialize:", init["result"]["serverInfo"], "| protocol:", init["result"]["protocolVersion"])

    tools = [t["name"] for t in rpc(2, "tools/list")["result"]["tools"]]
    print("tools:", tools)
    assert tools == ["py_exec", "py_reset"], tools

    r1 = rpc(3, "tools/call", {"name": "py_exec", "arguments": {"code": "import os\nx = 41\nprint(os.getcwd())", "cwd": BASE}})
    t1 = r1["result"]["content"][0]["text"]
    print("py_exec #1:", t1.replace("\n", " | "))
    assert os.path.normcase(BASE) in os.path.normcase(t1)

    r2 = rpc(4, "tools/call", {"name": "py_exec", "arguments": {"code": "print(x + 1, os.getcwd())"}})
    t2 = r2["result"]["content"][0]["text"]
    print("py_exec #2:", t2.replace("\n", " | "))
    assert "42" in t2 and os.path.normcase(BASE) in os.path.normcase(t2)

    r3 = rpc(5, "tools/call", {"name": "py_exec", "arguments": {"code": "1", "cwd": os.path.join(BASE, "_does_not_exist_")}})
    print("py_exec bad cwd:", r3["result"]["content"][0]["text"])
    assert r3["result"]["isError"] is True

    r4 = rpc(6, "tools/call", {"name": "py_exec", "arguments": {"code": "print('before error')\nraise ValueError('test error')"}})
    print("py_exec error:", r4["result"]["content"][0]["text"].splitlines()[-1][:120])
    assert r4["result"]["isError"] is True
    assert "before error" in r4["result"]["content"][0]["text"]

    r_feat = rpc(
        7,
        "tools/call",
        {
            "name": "py_exec",
            "arguments": {
                "code": (
                    "import inspect, subprocess, sys\n"
                    "assert sys.stdout.encoding == 'utf-8'\n"
                    "def _f(x): return x + 1\n"
                    "assert 'return x + 1' in inspect.getsource(_f)\n"
                    "p = subprocess.run([sys.executable, '-c', 'print(\"Việt Nam\")'], capture_output=True, text=True, encoding='utf-8')\n"
                    "assert p.returncode == 0 and 'Việt Nam' in p.stdout, p.stderr\n"
                    "print(chr(10).join(f'L{i:04d}_' + 'x'*50 for i in range(1100)))"
                )
            },
        },
    )
    t_feat = r_feat["result"]["content"][0]["text"]
    assert r_feat["result"]["isError"] is False, t_feat[:300]
    assert len(t_feat) <= 50100 and "[truncated " in t_feat and "L1099_" in t_feat.splitlines()[-2], (
        len(t_feat),
        t_feat[:200],
        t_feat[-120:],
    )

    r_val = rpc(8, "tools/call", {"name": "py_exec", "arguments": {"code": "x + 1"}})
    assert r_val["result"]["isError"] is False and "[value] 42" in r_val["result"]["content"][0]["text"], r_val

    r_to = rpc(9, "tools/call", {"name": "py_exec", "arguments": {"code": "import time; time.sleep(3)", "timeout": 1}})
    print("py_exec timeout:", r_to["result"]["content"][0]["text"])
    assert r_to["result"]["isError"] is True and "Timed out" in r_to["result"]["content"][0]["text"]

    r5 = rpc(10, "tools/call", {"name": "py_reset", "arguments": {}})
    print("py_reset:", r5["result"]["content"][0]["text"])

    r6 = rpc(11, "tools/call", {"name": "py_exec", "arguments": {"code": "import os; print('x' in globals(), os.getcwd())"}})
    t6 = r6["result"]["content"][0]["text"]
    assert "False" in t6 and os.path.normcase(BASE) in os.path.normcase(t6), t6

    proc.stdin.close()
    proc.wait(timeout=10)
    print("server exit:", proc.returncode)
    assert proc.returncode == 0
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
