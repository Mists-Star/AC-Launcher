"""IA path table generator — docs that can't silently drift.

Reads ``# ia[page]: 操作 | 层/组件 | 结果与反馈 [| 备注]`` markers from
``src/**.py`` and writes ``docs/ia/paths.md``. ``--check`` compares the
generated output with the file on disk and fails when it is stale, so
``regress.py`` catches "code changed, doc didn't".

Usage::

    python tools/gen_paths.py           # regenerate
    python tools/gen_paths.py --check   # verify (used by tests/check_paths.py)
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "src")
DOC = os.path.join(HERE, "docs", "ia", "paths.md")

MARK = re.compile(r"^\s*#\s*ia\[([a-z0-9_-]+)\]:\s*(.+)$")

# Display order / titles; unknown pages still render, sorted after these.
PAGE_TITLES = {
    "home": "首页",
    "instances": "实例",
    "settings": "设置",
    "diagnostics": "诊断",
}


def collect() -> tuple[dict[str, list[tuple[str, int, list[str]]]], list[str]]:
    """Return ``({page: [(file, line, cols)]}, errors)``."""
    pages: dict[str, list[tuple[str, int, list[str]]]] = {}
    errors: list[str] = []
    for root, _dirs, files in os.walk(SRC):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, HERE).replace(os.sep, "/")
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError as exc:
                errors.append(f"{rel}: 读取失败 {exc}")
                continue
            for lineno, raw in enumerate(lines, 1):
                m = MARK.match(raw.rstrip("\n"))
                if not m:
                    continue
                cols = [c.strip() for c in m.group(2).split("|")]
                if len(cols) < 3 or not cols[0] or not cols[1] or not cols[2]:
                    errors.append(
                        f"{rel}:{lineno}: 需要「操作 | 层/组件 | 结果」，实际：{m.group(2)}"
                    )
                    continue
                if len(cols) > 4:
                    errors.append(
                        f"{rel}:{lineno}: 最多 4 列（操作 | 层/组件 | 结果 | 备注）"
                    )
                    continue
                pages.setdefault(m.group(1), []).append((rel, lineno, cols))
    return pages, errors


def render() -> str:
    pages, errors = collect()
    out = [
        "# AC 用户路径表（自动生成）",
        "",
        "> 由 `tools/gen_paths.py` 从源码里的 "
        "`# ia[page]: 操作 | 层/组件 | 结果与反馈 [| 备注]` 标记生成。",
        "> **不要手改本文件**：改代码后重跑生成器；`regress.py` 会检查是否过期。",
        "",
    ]
    if errors:
        out.append("## ⚠ 标记错误")
        out.append("")
        for err in errors:
            out.append(f"- {err}")
        out.append("")
    known = [p for p in PAGE_TITLES if p in pages]
    rest = sorted(p for p in pages if p not in PAGE_TITLES)
    for page in known + rest:
        out.append(f"## {PAGE_TITLES.get(page, page)}（`{page}`）")
        out.append("")
        out.append("| 操作 | 层/组件 | 结果与反馈 | 备注 |")
        out.append("| --- | --- | --- | --- |")
        for rel, lineno, cols in sorted(pages[page], key=lambda r: (r[0], r[1])):
            note = cols[3] if len(cols) > 3 else ""
            # 只记文件不记行号：行号会随任意编辑漂移，导致文档天天「过期」；
            # 标记增删改才是需要校验的内容。
            src = f"`{rel}`"
            note = (note + " " if note else "") + src
            out.append(f"| {cols[0]} | {cols[1]} | {cols[2]} | {note.strip()} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        try:
            with open(DOC, encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            print(f"缺少 {os.path.relpath(DOC, HERE)}，请运行 python tools/gen_paths.py")
            return 1
        if current != text:
            print(f"过期：{os.path.relpath(DOC, HERE)} 与源码标记不一致，"
                  "请运行 python tools/gen_paths.py")
            return 1
        pages, errors = collect()
        print(f"IA 路径表最新：{len(pages)} 页 / "
              f"{sum(len(v) for v in pages.values())} 条 / {len(errors)} 错误")
        return 0 if not errors else 1
    os.makedirs(os.path.dirname(DOC), exist_ok=True)
    with open(DOC, "w", encoding="utf-8") as f:
        f.write(text)
    pages, errors = collect()
    print(f"已生成 {os.path.relpath(DOC, HERE)}：{len(pages)} 页 / "
          f"{sum(len(v) for v in pages.values())} 条 / {len(errors)} 错误")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
