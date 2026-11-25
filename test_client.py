#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Comprehensive test suite for Code Mode Antigravity v2 over MCP stdio JSON-RPC."""
import json
import os
import subprocess
import sys
import time

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

    def send_raw(req_id, method, params=None):
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def recv_raw():
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("Server did not respond: %s" % proc.stderr.read())
        return json.loads(line)

    def rpc(req_id, method, params=None):
        send_raw(req_id, method, params)
        return recv_raw()

    init = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}})
    print("initialize:", init["result"]["serverInfo"], "| protocol:", init["result"]["protocolVersion"])
    assert init["result"]["serverInfo"]["version"] == "2.0.0", init

    tools = [t["name"] for t in rpc(2, "tools/list")["result"]["tools"]]
    print("tools:", tools)
    assert tools == ["py_exec", "py_reset"], tools

    # 1. Basic state + hide [value] None
    r1 = rpc(3, "tools/call", {"name": "py_exec", "arguments": {"code": "import os\nx = 41\nprint(os.getcwd())", "cwd": BASE}})
    t1 = r1["result"]["content"][0]["text"]
    print("py_exec #1:", t1.replace("\n", " | "))
    assert os.path.normcase(BASE) in os.path.normcase(t1)
    assert "[value] None" not in t1, "Should hide [value] None: " + t1

    r2 = rpc(4, "tools/call", {"name": "py_exec", "arguments": {"code": "print(x + 1, os.getcwd())"}})
    t2 = r2["result"]["content"][0]["text"]
    assert "42" in t2 and os.path.normcase(BASE) in os.path.normcase(t2) and "[value] None" not in t2

    # 2. Value still shown when non-None
    r_val = rpc(5, "tools/call", {"name": "py_exec", "arguments": {"code": "x + 1"}})
    assert r_val["result"]["isError"] is False and "[value] 42" in r_val["result"]["content"][0]["text"], r_val

    # 3. Built-in helpers: find_files, grep, read_json, tree, state
    r_help = rpc(
        6,
        "tools/call",
        {
            "name": "py_exec",
            "arguments": {
                "code": (
                    "py_files = find_files('*.py')\n"
                    "hits = grep('SERVER_VERSION', glob='server.py')\n"
                    "pj = read_json('plugin/plugin.json')\n"
                    "tr = tree('.', max_depth=2)\n"
                    "st = state()\n"
                    "assert 'server.py' in py_files and 'worker.py' in py_files, py_files\n"
                    "assert any('2.0.0' in h[2] for h in hits), hits\n"
                    "assert isinstance(pj, dict) and 'name' in pj, pj\n"
                    "assert 'plugin/' in tr, tr\n"
                    "assert 'Session RAM:' in st and 'py_files' in st, st\n"
                    "print('HELPERS_OK', len(py_files), len(hits))"
                )
            },
        },
    )
    t_help = r_help["result"]["content"][0]["text"]
    print("helpers:", t_help)
    assert r_help["result"]["isError"] is False and "HELPERS_OK" in t_help, t_help

    # 4. Smart Overflow -> saved in _last_out
    r_ov = rpc(
        7,
        "tools/call",
        {
            "name": "py_exec",
            "arguments": {
                "code": "print('\\n'.join(f'L{i:04d}_' + 'x'*50 for i in range(600)))",
                "max_chars": 4000,
            },
        },
    )
    t_ov = r_ov["result"]["content"][0]["text"]
    print("overflow len:", len(t_ov))
    assert r_ov["result"]["isError"] is False, t_ov[:300]
    assert "[overflow:" in t_ov and "_last_out" in t_ov and "L0599_" in t_ov, t_ov[-200:]

    r_ov2 = rpc(
        8,
        "tools/call",
        {
            "name": "py_exec",
            "arguments": {"code": "lines = _last_out.splitlines()\nprint(len(lines), lines[300][:10])"},
        },
    )
    t_ov2 = r_ov2["result"]["content"][0]["text"]
    print("_last_out filter:", t_ov2)
    assert "600 L0300_" in t_ov2, t_ov2

    # 5. Parallel named sessions + isolation
    t0 = time.perf_counter()
    send_raw(9, "tools/call", {"name": "py_exec", "arguments": {"session": "alpha", "code": "import time; tag='A'; time.sleep(0.45); print(tag)"}})
    send_raw(10, "tools/call", {"name": "py_exec", "arguments": {"session": "beta", "code": "import time; tag='B'; time.sleep(0.45); print(tag)"}})
    res_a = recv_raw()
    res_b = recv_raw()
    elapsed = time.perf_counter() - t0
    by_id = {res_a["id"]: res_a, res_b["id"]: res_b}
    print(f"parallel sessions elapsed: {elapsed:.2f}s | alpha={by_id[9]['result']['content'][0]['text']} | beta={by_id[10]['result']['content'][0]['text']}")
    assert by_id[9]["result"]["content"][0]["text"] == "A"
    assert by_id[10]["result"]["content"][0]["text"] == "B"
    assert elapsed < 0.85, f"Expected parallel execution < 0.85s, got {elapsed:.2f}s"

    # Verify isolation between alpha and beta
    r_iso = rpc(11, "tools/call", {"name": "py_exec", "arguments": {"session": "alpha", "code": "print(tag, 'x' in globals())"}})
    assert r_iso["result"]["content"][0]["text"] == "A False", r_iso

    # 6. Worker crash captures real stderr
    r_crash = rpc(
        12,
        "tools/call",
        {
            "name": "py_exec",
            "arguments": {"session": "beta", "code": "import os; os.write(2, b'FATAL_NATIVE_BOOM\\n'); os._exit(2)"},
        },
    )
    t_crash = r_crash["result"]["content"][0]["text"]
    print("crash stderr capture:", t_crash.replace("\n", " | "))
    assert r_crash["result"]["isError"] is True and "FATAL_NATIVE_BOOM" in t_crash, t_crash

    # 7. Error handling & bad cwd & timeout
    r_bad = rpc(13, "tools/call", {"name": "py_exec", "arguments": {"code": "1", "cwd": os.path.join(BASE, "_no_such_dir_")}})
    assert r_bad["result"]["isError"] is True

    r_to = rpc(14, "tools/call", {"name": "py_exec", "arguments": {"session": "beta", "code": "import time; time.sleep(3)", "timeout": 1}})
    assert r_to["result"]["isError"] is True and "Timed out" in r_to["result"]["content"][0]["text"]

    # 8. Reset single session vs all sessions
    r_rst1 = rpc(15, "tools/call", {"name": "py_reset", "arguments": {"session": "alpha"}})
    assert "alpha" in r_rst1["result"]["content"][0]["text"]
    r_chk = rpc(16, "tools/call", {"name": "py_exec", "arguments": {"session": "alpha", "code": "print('tag' in globals())"}})
    assert r_chk["result"]["content"][0]["text"] == "False"

    r_rst_all = rpc(17, "tools/call", {"name": "py_reset", "arguments": {"session": "*"}})
    assert "All" in r_rst_all["result"]["content"][0]["text"]
    r_chk_def = rpc(18, "tools/call", {"name": "py_exec", "arguments": {"code": "print('x' in globals())"}})
    assert r_chk_def["result"]["content"][0]["text"] == "False"

    proc.stdin.close()
    proc.wait(timeout=10)
    print("server exit:", proc.returncode)
    assert proc.returncode == 0
    print("ALL V2 CHECKS PASSED")


if __name__ == "__main__":
    main()
