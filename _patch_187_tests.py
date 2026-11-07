import io

p = "tests/test_round183_editor.py"
s = io.open(p, encoding="utf-8").read()

old = '''for key in ("basic", "launch", "modify", "java", "dir", "mods", "content",
            "adv"):
    check("有 %-8s 页构建函数" % key, "def _page_%s(" % key in editor_src)

nav_keys = re.findall(r'\\("(\\w+)", "inst\\.tab_(\\w+)", "(\\w+)"\\)', editor_src)
check("导航项 8 个", len(nav_keys) == 8, str(len(nav_keys)))
check("导航项与页函数一一对应",
      {k for k, _t, _i in nav_keys} == {"basic", "launch", "modify", "java",
                                        "dir", "mods", "content", "adv"})'''
new = '''for key in ("overview", "setup", "modify", "mods", "content"):
    check("有 %-8s 页构建函数" % key, "def _page_%s(" % key in editor_src)

nav_keys = re.findall(r'\\("(\\w+)", "inst\\.tab_(\\w+)", "(\\w+)"\\)', editor_src)
check("导航项 5 个", len(nav_keys) == 5, str(len(nav_keys)))
check("导航项与页函数一一对应",
      {k for k, _t, _i in nav_keys} == {"overview", "setup", "modify",
                                        "mods", "content"})'''
assert s.count(old) == 1
s = s.replace(old, new)

old2 = '''_launch_body = editor_src.split("def _page_launch(", 1)[-1].split(
    "def _page_modify(", 1)[0]
check("启动页不再放加载器下拉", "loader_combo" not in _launch_body)'''
new2 = '''# round-187 重排后「启动/Java/目录」三页并进「设置」：旧页函数必须退役，
# 否则就是两套字段两个来源
check("旧三页函数已退役",
      all(("def _page_%s(" % k) not in editor_src
          for k in ("basic", "launch", "java", "dir", "adv")))'''
assert s.count(old2) == 1
s = s.replace(old2, new2)

s = s.replace('check("八个页都建出来了", dlg.stack.count() == 8, str(dlg.stack.count()))',
              'check("五个页都建出来了", dlg.stack.count() == 5, str(dlg.stack.count()))')
s = s.replace('check("导航行数 = 8", dlg.nav.count() == 8, str(dlg.nav.count()))',
              'check("导航行数 = 5", dlg.nav.count() == 5, str(dlg.nav.count()))')

# 概览页新能力
old3 = '''check("模组面板有搜索框", dlg.mod_panel.search.placeholderText() != "")'''
new3 = '''check("概览页有只读状态卡", hasattr(dlg, "status_box") and
      bool(dlg.status_box.toPlainText() if hasattr(dlg.status_box, "toPlainText")
           else dlg.status_box.text()))
check("概览页有导出整合包入口", "instances.export_pack" in editor_src)
check("模组面板有搜索框", dlg.mod_panel.search.placeholderText() != "")'''
assert s.count(old3) == 1
s = s.replace(old3, new3)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("tests updated")
