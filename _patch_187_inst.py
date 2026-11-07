import io

p = "src/instances.py"
s = io.open(p, encoding="utf-8").read()

# 1) 字段
old = '''    game_dir_override: str = ""  # isolation == "custom" 时的自定义游戏目录（绝对路径）'''
new = '''    game_dir_override: str = ""  # isolation == "custom" 时的自定义游戏目录（绝对路径）
    # round-187 实例级「自动进入服务器」：形如 "ip:端口"。启动时自动追加
    # --server/--port（PCL 同名能力）。留空 = 不自动进。
    auto_server: str = ""'''
assert s.count(old) == 1
s = s.replace(old, new)

# 2) 反序列化
old2 = '''            game_dir_override=raw.get("game_dir_override", "") or "",'''
new2 = '''            game_dir_override=raw.get("game_dir_override", "") or "",
            auto_server=raw.get("auto_server", "") or "",'''
assert s.count(old2) == 1
s = s.replace(old2, new2)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("instance ok")
