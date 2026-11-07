import io

p = "src/instance_editor.py"
s = io.open(p, encoding="utf-8").read()

block = io.open("_restore_java.txt", encoding="utf-8").read()
anchor = "    # ── ⑤ 模组 ──────────────────────────────────────────────"
assert s.count(anchor) == 1
s = s.replace(anchor, block + anchor)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("java helpers restored")
