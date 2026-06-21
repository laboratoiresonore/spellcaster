"""One-shot migration: rewrite antenna's subprocess.run / Popen calls to use
the _silent helper, so the heartbeat (and every cold-path call) stops flashing
cmd windows on Windows pythonw.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "antenna"

SKIP = {"firewall.py", "install_shortcuts.py", "service_launcher.py",
        "_silent.py", "__init__.py", "__main__.py"}

HAS_IMPORT = re.compile(r"^from \. import _silent\b", re.MULTILINE)
IMPORT_LINE = re.compile(r"^(import subprocess\b.*)$", re.MULTILINE)


def looks_like_string_literal(line: str, col: int) -> bool:
    before = line[:col]
    before_clean = before.replace("\\'", "").replace('\\"', "")
    single = before_clean.count("'") - before_clean.count("'''")
    double = before_clean.count('"') - before_clean.count('"""')
    return (single % 2 == 1) or (double % 2 == 1)


def rewrite_calls(src: str) -> tuple[str, int]:
    out = []
    n = 0
    last = 0
    for m in re.finditer(r"\bsubprocess\.(run|Popen)\(", src):
        out.append(src[last:m.start()])
        line_start = src.rfind("\n", 0, m.start()) + 1
        line_end = src.find("\n", m.start())
        if line_end == -1:
            line_end = len(src)
        line = src[line_start:line_end]
        col = m.start() - line_start
        if looks_like_string_literal(line, col):
            out.append(m.group(0))
        else:
            verb = m.group(1)
            out.append(f"_silent.{verb}(")
            n += 1
        last = m.end()
    out.append(src[last:])
    return "".join(out), n


def inject_import(src: str) -> str:
    if HAS_IMPORT.search(src):
        return src
    matches = list(IMPORT_LINE.finditer(src))
    if not matches:
        return src
    last = matches[-1]
    insert_at = last.end()
    return src[:insert_at] + "\nfrom . import _silent" + src[insert_at:]


def process_file(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    if "subprocess.run(" not in src and "subprocess.Popen(" not in src:
        return {"path": path.name, "calls": 0, "skipped": "no subprocess calls"}
    new_src, n = rewrite_calls(src)
    if n == 0:
        return {"path": path.name, "calls": 0, "skipped": "all in strings"}
    new_src = inject_import(new_src)
    path.write_text(new_src, encoding="utf-8")
    return {"path": path.name, "calls": n, "skipped": None}


def main():
    for f in sorted(ROOT.rglob("*.py")):
        if f.name in SKIP or "__pycache__" in f.parts:
            continue
        r = process_file(f)
        tag = r["skipped"] or f"rewrote {r['calls']} call(s)"
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        print(f"  {rel}: {tag}")


if __name__ == "__main__":
    main()
