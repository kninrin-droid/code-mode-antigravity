# Code Mode (`py_exec`)

- Batch multi-file reads, filtering, JSON/CSV inspection, or repetitive checks into **one `py_exec` call** (pass `cwd` on the first call).
- Built-in helpers are preloaded: `find_files(pattern, root, limit)`, `grep(pattern, root, glob)`, `read_json(path)`, `tree(root, max_depth)`, and `state()` (check RAM/variables).
- Only `print()` summaries or key lines. If stdout exceeds `max_chars` (default 12,000), the full output is saved in `_last_out` — filter `_last_out` in the next call instead of re-running heavy work.
- Reuse variables across calls; pass `session="<name>"` to isolate parallel work; call `py_reset` (or `session="*"`) when switching tasks or clearing heavy RAM.
- Keep using dedicated tools for single-file edits (`edit_file`), browser work, or long-running shell commands (`run_command`).
