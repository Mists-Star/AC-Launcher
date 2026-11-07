import io

p = "src/instance_editor.py"
s = io.open(p, encoding="utf-8").read()

block = io.open("_restore_block.txt", encoding="utf-8").read()
# 去掉误截进来的尾部（"# ── ⑤ 模组" 注释与空行）
block = block.replace("    # ── ⑤ 模组 ──────────────────────────────────────────────\n", "")
block = block.replace("        self._refresh_status()\n\n    def _pick_game_dir", "    def _pick_game_dir")

anchor = "    # ── ⑤ 模组 ──────────────────────────────────────────────"
assert s.count(anchor) == 1
s = s.replace(anchor, block + anchor)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("helpers restored")
