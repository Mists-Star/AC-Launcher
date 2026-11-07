import io

p = "src/instance_editor.py"
s = io.open(p, encoding="utf-8").read()

# 删掉死代码：旧 _page_java 与 _page_dir 的页函数体
# （其辅助方法 _load_java_list / _fill_java_combo / _browse_java /
#   _load_java_plan / _update_fmt_hint / _refresh_marker / _recheck_marker /
#   _pick_game_dir 都被新「设置」页使用，必须保留）
start = s.index("    # ── ④ Java ──────────────────────────────────────────────")
end = s.index("    # ── ④ 目录与格式 ────────────────────────────────────────")
s = s[:start] + s[end:]

start = s.index("    # ── ④ 目录与格式 ────────────────────────────────────────")
end = s.index("    # ── ⑤ 模组 ──────────────────────────────────────────────")
s = s[:start] + s[end:]

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("dead code removed")
