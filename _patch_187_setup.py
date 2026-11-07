import io

p = "src/instance_editor.py"
s = io.open(p, encoding="utf-8").read()

# ── 1) 设置页：内存条 + 分配提示 ────────────────────────────────────────
old = '''        self.mem_spin.setSuffix(t("inst.mem_suffix"))
        p.row(t("instances.setting_mem"), self.mem_spin)'''
new = '''        self.mem_spin.setSuffix(t("inst.mem_suffix"))
        p.row(t("instances.setting_mem"), self.mem_spin)

        # round-187 内存可视化条（PCL 同款）：其他程序已用 | 本实例分配 | 剩余。
        # 有它才看得清「4 GB 到底够不够」—— 一个孤零零的数字没这个信息量。
        self.mem_bar = _MemBar()
        self.mem_bar.set_values(int(inst.ram_mb or 0))
        p.add(self.mem_bar)
        self.mem_info_lbl = QLabel("")
        self.mem_info_lbl.setStyleSheet(_SUB_STYLE)
        self.mem_info_lbl.setWordWrap(True)
        p.add(self.mem_info_lbl)
        self._refresh_mem_info()
        self.mem_spin.valueChanged.connect(self._on_mem_changed)'''
assert s.count(old) == 1
s = s.replace(old, new)

# ── 2) 服务器区（自动进入服务器字段）+ _collect 写回 ─────────────────────
old2 = '''        # ── 启动前后命令 ──
        p.section(t("inst.hooks_section"))'''
new2 = '''        # ── 服务器 ──
        p.section(t("inst.server_section"))
        self.auto_server_edit = p.field(t("inst.auto_server_label"))
        self.auto_server_edit.setText((inst.auto_server or "").strip())
        self.auto_server_edit.setPlaceholderText(t("inst.auto_server_ph"))
        p.hint(t("inst.auto_server_hint"))

        # ── 启动前后命令 ──
        p.section(t("inst.hooks_section"))'''
assert s.count(old2) == 1
s = s.replace(old2, new2)

old3 = '''        inst.post_launch_cmd = self.post_cmd_edit.text().strip()
        inst.exit_cmd = self.exit_cmd_edit.text().strip()'''
new3 = '''        inst.post_launch_cmd = self.post_cmd_edit.text().strip()
        inst.exit_cmd = self.exit_cmd_edit.text().strip()
        inst.auto_server = self.auto_server_edit.text().strip()'''
assert s.count(old3) == 1
s = s.replace(old3, new3)

# ── 3) 概览页：补全文件按钮 ─────────────────────────────────────────────
old4 = '''        mg.addWidget(ui_kit.make_button(
            t("instances.export_pack"), kind="secondary", icon_key="export",
            on_click=self._export_pack, min_h=32))
        mg.addStretch(1)'''
new4 = '''        mg.addWidget(ui_kit.make_button(
            t("instances.export_pack"), kind="secondary", icon_key="export",
            on_click=self._export_pack, min_h=32))
        # PCL「补全文件」同款：校验游戏文件完整性并重下缺失/损坏的
        mg.addWidget(ui_kit.make_button(
            t("inst.repair_files"), kind="secondary", icon_key="repair",
            on_click=self._repair_files, min_h=32))
        mg.addStretch(1)'''
assert s.count(old4) == 1
s = s.replace(old4, new4)

old5 = '''    def _export_pack(self) -> None:'''
new5 = '''    def _repair_files(self) -> None:
        """PCL「补全文件」同款：校验 + 重下缺失/损坏的游戏文件。

        复用 install_instance 的幂等补全（启动前自动修复走的就是它），
        这里只是给玩家一个手动入口，不用等启动失败才知道文件缺了。
        """
        if self._busy:
            return
        from .core.install import install_instance
        self._set_busy(True, t("inst.repair_working"))
        self._repair_worker = ProgressWorker(
            install_instance, self._inst,
            java_auto=True, java_path="", mirror="official", proxy="")
        self._repair_worker.finished.connect(self._on_repair_done)
        self._repair_worker.error.connect(self._on_repair_failed)
        self._repair_worker.start()

    def _on_repair_done(self, _result) -> None:
        self._set_busy(False, "")
        toast(self, t("inst.repair_files"), t("inst.repair_done"))

    def _on_repair_failed(self, err: str) -> None:
        self._set_busy(False, "")
        warn(self, t("inst.repair_files"), t("inst.repair_failed", e=str(err)))

    def _export_pack(self) -> None:'''
assert s.count(old5) == 1
s = s.replace(old5, new5)

# ── 4) 内存信息刷新方法（挂在 mem_spin 变化上）─────────────────────────
old6 = '''    def _repair_files(self) -> None:'''
new6 = '''    def _on_mem_changed(self, value: int) -> None:
        self.mem_bar.set_values(int(value))
        self._refresh_mem_info()

    def _refresh_mem_info(self) -> None:
        """内存条下的一行说明；分配超过 85% 系统内存时黄字提醒。"""
        game_mb = int(self.mem_spin.value() or 0)
        total, avail = _sys_memory_bytes()
        total_gb = total / (1024 ** 3)
        avail_gb = avail / (1024 ** 3)
        txt = t("inst.mem_info", total="%.1f" % total_gb,
                avail="%.1f" % avail_gb, game="%.1f" % (game_mb / 1024.0))
        # PCL 同款护栏：分配 > 85% 物理内存大概率把系统挤死
        if total and game_mb * 1024 * 1024 > total * 0.85:
            self.mem_info_lbl.setStyleSheet(
                "font-size:11px;color:%s;" % COLORS["warning"])
            txt += " " + t("inst.mem_too_big")
        else:
            self.mem_info_lbl.setStyleSheet(_SUB_STYLE)
        self.mem_info_lbl.setText(txt)

    def _repair_files(self) -> None:'''
assert s.count(old6) == 1
s = s.replace(old6, new6)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("setup ok")
