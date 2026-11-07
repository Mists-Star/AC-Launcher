import io

p = "src/instance_editor.py"
s = io.open(p, encoding="utf-8").read()

anchor = "# 导航项：(key, 标题键, 图标键)"
code = io.open("_membar_code.txt", encoding="utf-8").read()
assert s.count(anchor) == 1
s = s.replace(anchor, code)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("membar ok")
