import io

p = "src/instance_editor.py"
s = io.open(p, encoding="utf-8").read()

# 把误删的 _refresh_status 加回（放在 _page_overview 之后）
anchor = "    def _page_setup(self) -> _Page:"
restore = '''    def _refresh_status(self) -> None:
        """把「版本 / 加载器 / 格式 / 目录」画成一张只读信息卡。"""
        inst = self._inst
        try:
            fmt = detect_format(inst)
        except Exception:  # noqa: BLE001
            fmt = "auto"
        try:
            d = layout_of(inst)
            install_dir = d.get("install_dir") or inst.mc_dir
            layout_txt = inst.mc_dir
            extra = (" · " + t("inst.from_marker")) if d.get("from_marker") else ""
        except Exception:  # noqa: BLE001
            install_dir = inst.mc_dir
            layout_txt = inst.mc_dir
            extra = ""
        rows = (
            (t("inst.status_version"), inst.game_version or "-"),
            (t("inst.status_loader"), ("%s %s" % (
                loader_name(inst.loader or "vanilla"),
                inst.loader_version or "")).strip()),
            (t("inst.status_format"), "%s%s" % (t("instances.fmt_" + fmt), extra)),
        )
        # 三行两列（标签 | 值），路径单独段落——全部「标签换行 + 值」堆叠会
        # 拉出半屏高的小灰字墙（第一版实测）。
        html = ["<table cellspacing='0' cellpadding='1'>"]
        for k, v in rows:
            html.append(
                "<tr><td style='color:%s;padding-right:18px'>%s</td>"
                "<td style='color:%s'>%s</td></tr>"
                % (COLORS["text_sub"], k, COLORS["text_main"], _esc(v)))
        html.append("</table>")
        for k, v in ((t("inst.status_dir"), layout_txt),
                     (t("inst.status_install_dir"), install_dir or "-")):
            html.append(
                "<div style='margin-top:7px'>"
                "<span style='color:%s;font-size:11px'>%s</span><br/>"
                "<span style='color:%s;font-size:11px'>%s</span></div>"
                % (COLORS["text_sub"], k, COLORS["text_main"], _esc(v)))
        self.status_box.setText("".join(html))
        if hasattr(self, "foot_lbl"):
            self.foot_lbl.setText(inst.mc_dir or "")

''' + anchor
assert s.count(anchor) == 1
s = s.replace(anchor, restore)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("restored")
