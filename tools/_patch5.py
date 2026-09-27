import pathlib

# ---------------------------------------------------------------- zapret panel
p = pathlib.Path("app/ui/pages/zapret_panel.py")
t = p.read_text(encoding="utf-8")

# Game Filter
old = '''    def _apply_game_filter(self) -> None:
        cfg = self.ctx.config.zapret
        cfg.game_tcp_range = self.game_tcp_edit.text().strip() or "1024-65535"
        cfg.game_udp_range = self.game_udp_edit.text().strip() or "1024-65535"
        self.ctx.save_config()
        try:
            self.ctx.zapret.apply_game_filter()
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
            return
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()
        self.log_view.append("[hub] Game Filter применён")
'''
new = '''    def _apply_game_filter(self) -> None:
        cfg = self.ctx.config.zapret
        cfg.game_tcp_range = self.game_tcp_edit.text().strip() or "1024-65535"
        cfg.game_udp_range = self.game_udp_edit.text().strip() or "1024-65535"
        self.ctx.save_config()
        try:
            self.ctx.zapret.apply_game_filter()
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
            show_toast(self, tr("zapret.game_applied_error"), "error")
            return
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()
        self.log_view.append("[hub] Game Filter применён")
        show_toast(
            self,
            tr("zapret.game_applied", mode=tr("zapret.game_mode_" + cfg.game_mode)),
            "success",
        )
'''
assert t.count(old) == 1, "game filter"
t = t.replace(old, new)

# IPSet
old = '''    def _on_ipset_changed(self, index: int) -> None:
        if self._loading:
            return
        mode = self.ipset_combo.currentData()
        if not mode:
            return
        self.ctx.config.zapret.ipset_mode = mode
        self.ctx.save_config()
        try:
            self.ctx.zapret.apply_ipset_mode(mode)
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
            return
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()
'''
new = '''    def _on_ipset_changed(self, index: int) -> None:
        if self._loading:
            return
        mode = self.ipset_combo.currentData()
        if not mode:
            return
        self.ctx.config.zapret.ipset_mode = mode
        self.ctx.save_config()
        try:
            self.ctx.zapret.apply_ipset_mode(mode)
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
            show_toast(self, tr("zapret.ipset_applied_error"), "error")
            return
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()
        show_toast(
            self, tr("zapret.ipset_applied", mode=tr("zapret.ipset_" + mode)), "success"
        )
'''
assert t.count(old) == 1, "ipset"
t = t.replace(old, new)

# сохранение пользовательского списка
old = '''        self.ctx.zapret.write_user_list(name, self.list_edit.toPlainText())
        self.log_view.append(f"[hub] {tr('zapret.list_saved')}: {name}")
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()
'''
new = '''        self.ctx.zapret.write_user_list(name, self.list_edit.toPlainText())
        self.log_view.append(f"[hub] {tr('zapret.list_saved')}: {name}")
        show_toast(self, tr("zapret.list_saved_toast", name=name), "success")
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()
'''
assert t.count(old) == 1, "user list"
t = t.replace(old, new)

# обновление списка IP
old = '''        try:
            message = self.ctx.zapret.update_ipset_list(proxy=proxy)
            self.log_view.append(f"[hub] {message}")
            self.reload()
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
'''
new = '''        try:
            message = self.ctx.zapret.update_ipset_list(proxy=proxy)
            self.log_view.append(f"[hub] {message}")
            show_toast(self, message, "success")
            self.reload()
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
            show_toast(self, str(exc), "error")
'''
assert t.count(old) == 1, "ipset update"
t = t.replace(old, new)

# импорт show_toast
old = "from ..widgets import (\n"
assert t.count(old) >= 1
if "show_toast" not in t.split("class ")[0]:
    # добавляем в первый импорт widgets
    idx = t.index(old)
    end = t.index(")", idx)
    block = t[idx:end]
    t = t[:end] + "    show_toast,\n" + t[end:]
p.write_text(t, encoding="utf-8")
print("zapret ok")

# ---------------------------------------------------------------- tgws panel
p = pathlib.Path("app/ui/pages/tgws_panel.py")
t = p.read_text(encoding="utf-8")
old = '''        self.ctx.save_config()
        self._refresh_link()
        self.info_banner.set_kind("success")
        self.info_banner.set_text(tr("tgws.config_applied"))
        if self.ctx.tgws.is_running():
            self.ctx.tgws.restart()
'''
new = '''        self.ctx.save_config()
        self._refresh_link()
        self.info_banner.set_kind("success")
        self.info_banner.set_text(tr("tgws.config_applied"))
        show_toast(self, tr("tgws.config_applied"), "success")
        if self.ctx.tgws.is_running():
            self.ctx.tgws.restart()
'''
assert t.count(old) == 1, "tgws apply"
t = t.replace(old, new)

if "show_toast" not in t.split("class ")[0]:
    idx = t.index("from ..widgets import")
    end = t.index(")", idx)
    t = t[:end] + "    show_toast,\n" + t[end:]
p.write_text(t, encoding="utf-8")
print("tgws ok")
