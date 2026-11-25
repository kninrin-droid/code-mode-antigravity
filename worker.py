#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Persistent Python worker for Code Mode Antigravity v2.

Features:
  - Preserves variables, imports, and functions across calls
  - Hides redundant [value] None outputs
  - Smart Overflow: saves long stdout into `_last_out` and returns head+tail preview
  - Built-in zero-dependency helpers: find_files, grep, read_json, tree, state
  - Bounded linecache so long sessions do not leak memory
"""
import ast
import fnmatch
import io
import json
import linecache
import os
import re
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", newline="\n")
sys.stdin.reconfigure(encoding="utf-8")

DEFAULT_MAX_CHARS = 12000
HARD_MAX_CHARS = 50000
MAX_LINECACHE_ENTRIES = 50
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "dist",
    "build",
}


def find_files(pattern="*", root=".", limit=200):
    """Find files matching glob pattern under root, skipping common noise dirs."""
    matches = []
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, name), root_abs)
            rel_posix = rel.replace("\\", "/")
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_posix, pattern):
                matches.append(rel_posix)
                if limit and len(matches) >= limit:
                    return matches
    return matches


def grep(pattern, root=".", glob="*", ignore_case=True, limit=100, max_file_bytes=2 * 1024 * 1024):
    """Search regex pattern across text files. Returns list of (path, line_no, text)."""
    flags = re.IGNORECASE if ignore_case else 0
    rx = re.compile(pattern, flags)
    hits = []
    root_abs = os.path.abspath(root)
    for rel in find_files(glob, root_abs, limit=0):
        full = os.path.join(root_abs, rel)
        try:
            if os.path.getsize(full) > max_file_bytes:
                continue
            with open(full, "rb") as fh:
                raw = fh.read()
            if b"\x00" in raw[:4096]:
                continue
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
        for idx, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append((rel, idx, line.strip()[:200]))
                if limit and len(hits) >= limit:
                    return hits
    return hits


def read_json(path):
    """Read and parse a UTF-8 JSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def tree(root=".", max_depth=3, limit=200):
    """Return a compact directory tree string, skipping common noise dirs."""
    root_abs = os.path.abspath(root)
    lines = [os.path.basename(root_abs) or root_abs]
    truncated = False

    def walk(cur, prefix, depth):
        nonlocal truncated
        if depth > max_depth or truncated:
            return
        try:
            entries = sorted(os.listdir(cur), key=lambda n: (not os.path.isdir(os.path.join(cur, n)), n.lower()))
        except OSError:
            return
        entries = [e for e in entries if e not in SKIP_DIRS]
        for idx, name in enumerate(entries):
            if len(lines) >= limit:
                truncated = True
                return
            full = os.path.join(cur, name)
            is_dir = os.path.isdir(full)
            connector = "+-- " if idx == len(entries) - 1 else "|-- "
            lines.append(prefix + connector + name + ("/" if is_dir else ""))
            if is_dir and depth < max_depth:
                ext = "    " if idx == len(entries) - 1 else "|   "
                walk(full, prefix + ext, depth + 1)

    walk(root_abs, "", 1)
    if truncated:
        lines.append("... (limit=%d reached)" % limit)
    return "\n".join(lines)


def _approx_size(obj, depth=0):
    """Shallow-bounded memory estimate in bytes without external deps."""
    size = sys.getsizeof(obj)
    if depth >= 2:
        return size
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:200]:
            size += _approx_size(k, depth + 1) + _approx_size(v, depth + 1)
    elif isinstance(obj, (list, tuple, set)):
        sample = list(obj)[:200]
        if sample:
            avg = sum(_approx_size(x, depth + 1) for x in sample) / len(sample)
            size += int(avg * len(obj))
    return size


def _fmt_bytes(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.2f MB" % (n / (1024.0 * 1024.0))


def state():
    """Return a summary of user variables kept in RAM and estimated size."""
    rows = []
    total = 0
    for k, v in sorted(STATE.items()):
        if k.startswith("__") or k in _BUILTIN_NAMES:
            continue
        sz = _approx_size(v)
        total += sz
        rows.append((k, type(v).__name__, _fmt_bytes(sz)))
    if not rows:
        return "Session RAM: empty (0 user variables)."
    lines = ["Session RAM: %d var(s), ~%s total" % (len(rows), _fmt_bytes(total))]
    for name, tname, sz_str in rows:
        lines.append("  - %s (%s): ~%s" % (name, tname, sz_str))
    return "\n".join(lines)


_HELPERS = {
    "find_files": find_files,
    "grep": grep,
    "read_json": read_json,
    "tree": tree,
    "state": state,
}
_BUILTIN_NAMES = set(_HELPERS.keys())

STATE = {"__name__": "__main__"}
STATE.update(_HELPERS)
_EXEC_SEQ = 0
_CACHE_KEYS = []


def _smart_overflow(text, limit):
    """Save overflowing stdout into `_last_out` and return a clean head+tail preview."""
    if len(text) <= limit:
        return text
    STATE["_last_out"] = text
    total_lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    half = max(200, int(limit * 0.45))
    head = text[:half]
    tail = text[-half:]
    head_nl = head.rfind("\n")
    if head_nl > 0:
        head = head[:head_nl]
    tail_nl = tail.find("\n")
    if tail_nl != -1 and tail_nl + 1 < len(tail):
        tail = tail[tail_nl + 1 :]
    note = (
        "\n... [overflow: %d chars / %d lines saved in _last_out; "
        "showing head+tail — filter _last_out in next py_exec] ...\n"
    ) % (len(text), total_lines)
    return head + note + tail


def execute(code, cwd=None, max_chars=DEFAULT_MAX_CHARS):
    global _EXEC_SEQ
    out_buf = io.BytesIO()
    err_buf = io.BytesIO()
    out = io.TextIOWrapper(out_buf, encoding="utf-8", errors="replace", newline="\n")
    err = io.TextIOWrapper(err_buf, encoding="utf-8", errors="replace", newline="\n")
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    value = None
    has_value = False
    ok = True
    try:
        if cwd:
            os.chdir(cwd)
        _EXEC_SEQ += 1
        filename = "<py_exec_%d>" % _EXEC_SEQ
        linecache.cache[filename] = (len(code), None, code.splitlines(keepends=True), filename)
        _CACHE_KEYS.append(filename)
        while len(_CACHE_KEYS) > MAX_LINECACHE_ENTRIES:
            old_key = _CACHE_KEYS.pop(0)
            linecache.cache.pop(old_key, None)

        tree_ast = ast.parse(code, filename, "exec")
        last_expr = None
        if tree_ast.body and isinstance(tree_ast.body[-1], ast.Expr):
            last_expr = tree_ast.body.pop()
        if tree_ast.body:
            exec(compile(tree_ast, filename, "exec"), STATE)
        if last_expr is not None:
            value = eval(compile(ast.Expression(last_expr.value), filename, "eval"), STATE)
            has_value = value is not None
    except BaseException:
        ok = False
        traceback.print_exc()
    finally:
        for stream in (out, err):
            if not stream.closed:
                stream.flush()
        sys.stdout, sys.stderr = old_out, old_err

    try:
        limit = int(max_chars)
    except (TypeError, ValueError):
        limit = DEFAULT_MAX_CHARS
    limit = max(500, min(limit, HARD_MAX_CHARS))

    stdout_text = _smart_overflow(out_buf.getvalue().decode("utf-8", "replace"), limit)
    stderr_text = err_buf.getvalue().decode("utf-8", "replace")
    return {
        "ok": ok,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "value": repr(value)[:20000] if has_value else None,
        "has_value": has_value,
    }


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except ValueError:
            sys.stdout.write(json.dumps({"ok": False, "error": "Invalid JSON"}, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        result = execute(
            request.get("code") or "",
            request.get("cwd") or None,
            request.get("max_chars", DEFAULT_MAX_CHARS),
        )
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
