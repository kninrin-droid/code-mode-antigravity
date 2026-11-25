#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Installer & diagnostics for Code Mode Antigravity MCP server and plugin rules.

Usage:
  python install_antigravity.py              # Dry run: print JSON snippet & detected paths
  python install_antigravity.py --write      # Install MCP entry + plugin rules (with backups)
  python install_antigravity.py --doctor     # Verify installation & run live JSON-RPC check
  python install_antigravity.py --uninstall  # Remove MCP entry + plugin rules (with backups)
"""
import json
import os
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
SERVER = os.path.join(BASE, "server.py")
WORKER = os.path.join(BASE, "worker.py")
PLUGIN_SRC = os.path.join(BASE, "plugin")
HOME = os.path.expanduser("~")

MCP_CANDIDATES = [
    os.path.join(HOME, ".gemini", "config", "mcp_config.json"),
    os.path.join(HOME, ".gemini", "antigravity", "mcp_config.json"),
    os.path.join(HOME, ".antigravity", "mcp.json"),
    os.path.join(HOME, "AppData", "Roaming", "Antigravity", "User", "mcp.json"),
    os.path.join(HOME, "AppData", "Roaming", "Antigravity IDE", "User", "mcp.json"),
    os.path.join(HOME, "Library", "Application Support", "Antigravity", "User", "mcp.json"),
    os.path.join(HOME, ".config", "Antigravity", "User", "mcp.json"),
]

PLUGIN_DIR = os.path.join(HOME, ".gemini", "config", "plugins", "code-mode")
BACKUP_DIR = os.path.join(HOME, ".gemini", "config", "backups")

ENTRY = {
    "command": PYTHON,
    "args": ["-u", SERVER],
    "tools": {
        "py_exec": {
            "eager": True,
        },
    },
}


def snippet():
    return json.dumps({"mcpServers": {"code-mode": ENTRY}}, ensure_ascii=False, indent=2)


def install_plugin():
    if not os.path.isdir(PLUGIN_SRC):
        print("Plugin folder not found, skipping:", PLUGIN_SRC)
        return
    plugins_root = os.path.dirname(PLUGIN_DIR)
    os.makedirs(plugins_root, exist_ok=True)
    for name in sorted(os.listdir(plugins_root)):
        src = os.path.join(plugins_root, name)
        if name.startswith("code-mode.bak-") and os.path.isdir(src):
            os.makedirs(BACKUP_DIR, exist_ok=True)
            dst = os.path.join(BACKUP_DIR, name)
            if os.path.exists(dst):
                dst = dst + "-" + time.strftime("%H%M%S")
            shutil.move(src, dst)
            print("Moved legacy plugin backup:", dst)
    if os.path.isdir(PLUGIN_DIR):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup = os.path.join(BACKUP_DIR, "code-mode.bak-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.copytree(PLUGIN_DIR, backup)
        print("Backed up plugin:", backup)
    shutil.copytree(PLUGIN_SRC, PLUGIN_DIR, dirs_exist_ok=True)
    print("Installed plugin:", PLUGIN_DIR)


def do_uninstall(no_plugin=False):
    removed_any = False
    found = [p for p in MCP_CANDIDATES if os.path.exists(p)]
    for path in found:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read().strip()
            data = json.loads(raw) if raw else {}
        except (OSError, ValueError) as exc:
            print("Skipped", path, "-", exc)
            continue
        servers = data.get("mcpServers")
        if isinstance(servers, dict) and "code-mode" in servers:
            backup = path + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(path, backup)
            print("Backed up MCP config:", backup)
            del servers["code-mode"]
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            print("Removed 'code-mode' from:", path)
            removed_any = True

    if not no_plugin and os.path.isdir(PLUGIN_DIR):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup = os.path.join(BACKUP_DIR, "code-mode.uninstalled-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.copytree(PLUGIN_DIR, backup)
        shutil.rmtree(PLUGIN_DIR)
        print("Backed up and removed plugin:", PLUGIN_DIR)
        print("Backup saved at:", backup)
        removed_any = True

    if not removed_any:
        print("Nothing to uninstall (no 'code-mode' MCP entry or plugin found).")
    else:
        print("\nUninstall complete. Restart Antigravity to apply changes.")
    return 0


def do_doctor():
    ok = True

    def check(cond, label, detail=""):
        nonlocal ok
        tag = "[OK]" if cond else "[!!]"
        if not cond:
            ok = False
        print("%s %s%s" % (tag, label, (" — " + detail) if detail else ""))

    check(os.path.exists(PYTHON), "Python interpreter", PYTHON)
    check(os.path.exists(SERVER), "server.py", SERVER)
    check(os.path.exists(WORKER), "worker.py", WORKER)

    mcp_installed = []
    for path in MCP_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            entry = (data.get("mcpServers") or {}).get("code-mode")
            if isinstance(entry, dict):
                mcp_installed.append((path, entry))
        except (OSError, ValueError):
            pass
    check(
        bool(mcp_installed),
        "MCP config registered",
        mcp_installed[0][0] if mcp_installed else "run --write to register",
    )
    if mcp_installed:
        args = mcp_installed[0][1].get("args") or []
        points_here = any(os.path.normcase(str(a)) == os.path.normcase(SERVER) for a in args)
        check(points_here, "MCP config points to this server.py", str(args))

    plugin_rules = os.path.join(PLUGIN_DIR, "rules", "AGENTS.md")
    check(os.path.isfile(plugin_rules), "Antigravity plugin rules", plugin_rules)

    # Live JSON-RPC smoke test against server.py
    live_ok = False
    live_detail = ""
    try:
        proc = subprocess.Popen(
            [PYTHON, "-u", SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            def rpc(req_id, method, params=None):
                msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
                if params is not None:
                    msg["params"] = params
                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("no response: " + proc.stderr.read())
                return json.loads(line)

            init = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "doctor"}})
            ver = init["result"]["serverInfo"]["version"]
            res = rpc(
                2,
                "tools/call",
                {"name": "py_exec", "arguments": {"code": "print(len(find_files('*.py')), state().splitlines()[0])", "cwd": BASE}},
            )
            txt = res["result"]["content"][0]["text"]
            rpc(3, "tools/call", {"name": "py_reset", "arguments": {"session": "*"}})
            live_ok = not res["result"].get("isError") and "Session RAM" in txt
            live_detail = "v%s | %s" % (ver, txt.replace("\n", " "))
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
            proc.wait(timeout=5)
    except Exception as exc:
        live_detail = str(exc)

    check(live_ok, "Live MCP JSON-RPC + helpers check", live_detail)
    print("\nDoctor result:", "HEALTHY" if ok else "ISSUES FOUND")
    return 0 if ok else 1


def main():
    write_mode = "--write" in sys.argv
    no_plugin = "--no-plugin" in sys.argv
    uninstall_mode = "--uninstall" in sys.argv
    doctor_mode = "--doctor" in sys.argv

    if doctor_mode:
        return do_doctor()
    if uninstall_mode:
        return do_uninstall(no_plugin=no_plugin)

    print("Python :", PYTHON)
    print("Server :", SERVER)
    print("Plugin :", PLUGIN_SRC)
    print("Exists :", os.path.exists(PYTHON), "/", os.path.exists(SERVER), "/", os.path.isdir(PLUGIN_SRC))
    print()
    print(snippet())
    print()

    found = [p for p in MCP_CANDIDATES if os.path.exists(p)]
    default_gemini_cfg = MCP_CANDIDATES[0]

    if not write_mode:
        if found:
            print("Detected MCP config file(s) (pass --write to update):")
            for p in found:
                print(" -", p)
        else:
            print("No existing Antigravity MCP config file found.")
            print("Pass --write to create/update ~/.gemini/config/mcp_config.json,")
            print("or paste the JSON snippet above into Settings > MCP.")
        if not no_plugin:
            print("Plugin target (installed with --write unless --no-plugin is passed):")
            print(" -", PLUGIN_DIR)
        return 0

    targets = found if found else [default_gemini_cfg]
    for path in targets:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    raw = fh.read().strip()
                data = json.loads(raw) if raw else {}
                if not isinstance(data, dict):
                    raise ValueError("JSON root is not an object")
                backup = path + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
                shutil.copy2(path, backup)
                print("Backed up MCP config:", backup)
            else:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                data = {}
        except (OSError, ValueError) as exc:
            print("Skipped", path, "-", exc)
            continue

        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            print("Skipped", path, "- mcpServers is not an object")
            continue
        servers["code-mode"] = ENTRY
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("Updated MCP config:", path)

    if not no_plugin:
        install_plugin()

    print("\nDone. Restart Antigravity to load the updated MCP tools and rules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
