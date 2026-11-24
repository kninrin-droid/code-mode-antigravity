#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Print or install the 'code-mode' MCP server and Antigravity plugin rules.

By default, performs a dry run and prints the generated MCP JSON snippet and
detected config paths. Pass --write to install the MCP entry (creates a .bak
backup first) and the bundled Antigravity plugin rules (skip with --no-plugin).
"""
import json
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
SERVER = os.path.join(BASE, "server.py")
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


def main():
    write_mode = "--write" in sys.argv
    no_plugin = "--no-plugin" in sys.argv

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
