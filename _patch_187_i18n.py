import io

# i18n：新页签 + 概览快捷方式
p = "src/i18n.py"
s = io.open(p, encoding="utf-8").read()

zh_anchor = '        "inst.tab_modify": "修改",\n'
zh_add = zh_anchor + '''        # round-187：8 页重排成 5 页（对齐 PCL 的 概览/设置/修改/Mod管理/内容）
        "inst.tab_overview": "概览",
        "inst.tab_setup": "设置",
        "inst.shortcuts_section": "快捷方式",
        "inst.manage_section": "高级管理",
        "inst.sc_game_dir": "打开游戏目录",
        "inst.sc_mods": "打开 mods",
        "inst.sc_saves": "打开存档",
'''
assert s.count(zh_anchor) == 1
s = s.replace(zh_anchor, zh_add)

en_anchor = '        "inst.tab_modify": "Modify",\n'
en_add = en_anchor + '''        # round-187: 8 pages -> 5 pages (PCL-style)
        "inst.tab_overview": "Overview",
        "inst.tab_setup": "Settings",
        "inst.shortcuts_section": "Shortcuts",
        "inst.manage_section": "Management",
        "inst.sc_game_dir": "Game folder",
        "inst.sc_mods": "Mods folder",
        "inst.sc_saves": "Saves folder",
'''
assert s.count(en_anchor) == 1
s = s.replace(en_anchor, en_add)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("i18n ok")
