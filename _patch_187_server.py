import io

p = "src/launch.py"
s = io.open(p, encoding="utf-8").read()

old = '''    # 游戏附加参数：--server/--port 走 mll 直连，其余令牌追加到命令尾部
    game_args = (getattr(inst, "game_args", "") or "").strip() \\
        or settings.get("game_args", "")
    _server, _port, extra_game = parse_game_args(game_args)
    if server_override:   # round-83 收藏服务器直连优先于附加参数里的 --server
        _server = server_override
        _port = port_override if port_override else _port'''
new = '''    # 游戏附加参数：--server/--port 走 mll 直连，其余令牌追加到命令尾部
    game_args = (getattr(inst, "game_args", "") or "").strip() \\
        or settings.get("game_args", "")
    # round-187 实例级「自动进入服务器」：填了 IP:端口 就相当于每次启动都带
    # --server/--port。优先级低于 round-83 的收藏服务器直连（一次性覆盖），
    # 高于全局 game_args —— 它是实例自己的属性，跟实例走。
    auto_server = (getattr(inst, "auto_server", "") or "").strip()
    if auto_server and not server_override and "--server" not in game_args:
        ip, _, port = auto_server.partition(":")
        if ip:
            game_args = (game_args + " --server " + ip).strip()
            if port.strip():
                game_args += " --port " + port.strip()
    _server, _port, extra_game = parse_game_args(game_args)
    if server_override:   # round-83 收藏服务器直连优先于附加参数里的 --server
        _server = server_override
        _port = port_override if port_override else _port'''
assert s.count(old) == 1
s = s.replace(old, new)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("launch ok")
