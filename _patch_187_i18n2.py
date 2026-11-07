import io

p = "src/i18n.py"
s = io.open(p, encoding="utf-8").read()

zh_anchor = '        "inst.sc_saves": "打开存档",\n'
zh_add = zh_anchor + '''        # round-187：功能补齐（内存可视化 / 自动进服 / 补全文件）
        "inst.mem_info": "系统内存 {total} GB · 可用 {avail} GB · 本实例分配 {game} GB",
        "inst.mem_too_big": "分配超过系统内存的 85%，启动大概率把系统挤死",
        "inst.server_section": "服务器",
        "inst.auto_server_label": "自动进入服务器",
        "inst.auto_server_ph": "IP:端口（留空 = 不自动进入）",
        "inst.auto_server_hint": "每次启动自动连到这个服务器；收藏服务器直连时以收藏为准",
        "inst.repair_files": "补全文件",
        "inst.repair_working": "正在校验并补全游戏文件…",
        "inst.repair_done": "游戏文件已校验并补全",
        "inst.repair_failed": "补全失败：{e}",
'''
assert s.count(zh_anchor) == 1
s = s.replace(zh_anchor, zh_add)

en_anchor = '        "inst.sc_saves": "Saves folder",\n'
en_add = en_anchor + '''        # round-187: memory bar / auto-join server / repair files
        "inst.mem_info": "System RAM {total} GB · free {avail} GB · this instance {game} GB",
        "inst.mem_too_big": "Over 85% of system RAM — the game will likely choke the PC",
        "inst.server_section": "Server",
        "inst.auto_server_label": "Auto-join server",
        "inst.auto_server_ph": "ip:port (empty = do not auto-join)",
        "inst.auto_server_hint": "Joins this server on every launch; a favorite-server direct connect overrides it",
        "inst.repair_files": "Repair files",
        "inst.repair_working": "Verifying and repairing game files…",
        "inst.repair_done": "Game files verified and repaired",
        "inst.repair_failed": "Repair failed: {e}",
'''
assert s.count(en_anchor) == 1
s = s.replace(en_anchor, en_add)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("i18n ok")
