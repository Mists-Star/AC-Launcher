import io

p = "src/instance_editor.py"
s = io.open(p, encoding="utf-8").read()

# warning 色键名修正 + ProgressWorker 局部导入
old = '''        if total and game_mb * 1024 * 1024 > total * 0.85:
            self.mem_info_lbl.setStyleSheet(
                "font-size:11px;color:%s;" % COLORS["warning"])
            txt += " " + t("inst.mem_too_big")'''
new = '''        if total and game_mb * 1024 * 1024 > total * 0.85:
            self.mem_info_lbl.setStyleSheet(
                "font-size:11px;color:%s;" % COLORS["danger"])
            txt += " " + t("inst.mem_too_big")'''
assert s.count(old) == 1
s = s.replace(old, new)

old2 = '''        if self._busy:
            return
        from .core.install import install_instance
        self._set_busy(True, t("inst.repair_working"))'''
new2 = '''        if self._busy:
            return
        from .core.install import install_instance
        from .worker import ProgressWorker
        self._set_busy(True, t("inst.repair_working"))'''
assert s.count(old2) == 1
s = s.replace(old2, new2)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("fixed")
