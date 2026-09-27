"""Главное окно приложения: боковое меню слева, страницы, мастер-кнопка.

Своей шапки нет — окном управляет стандартная рамка Windows.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import win32
from ..i18n import current_language, tr
from . import anim, icons, theme
from .app_icon import app_icon, app_pixmap
from .pages import ComponentsPage, DiagnosticsPage, HomePage, SettingsPage
from .tray import TrayManager
from .widgets import IconButton, StatusPill, show_toast

TITLES = {"zapret": "zapret-discord-youtube", "tgws": "TG WS Proxy"}


NAV_ITEMS = [
    "nav.home",
    "nav.components",
    "nav.diagnostics",
    "nav.settings",
]

# иконка для каждого пункта меню — показываются, когда боковая панель свёрнута
NAV_ICONS = {
    "nav.home": "grid",
    "nav.components": "layers",
    "nav.diagnostics": "activity",
    "nav.settings": "sliders",
}

# ширина боковой панели: раскрытая и свёрнутая (только иконки)
SIDEBAR_WIDTH = 248
SIDEBAR_WIDTH_COLLAPSED = 72

# индекс страницы по ключу меню — чтобы вставка раздела не ломала переходы
PAGE_INDEX = {key: index for index, key in enumerate(NAV_ITEMS)}


class MainWindow(QMainWindow):
    def __init__(self, ctx, tray_mode: bool = False):
        super().__init__()
        self.ctx = ctx
        self.tray_mode = tray_mode
        self.language = current_language()
        self.setWindowTitle(tr("app.name"))
        self.resize(1200, 840)
        self.setMinimumSize(980, 680)
        self.setProperty("theme_name", "dark")

        self.setWindowIcon(app_icon())

        self._animate = True
        self._diagnostics_busy = False
        self._collapsed = bool(self.ctx.config.general.sidebar_collapsed)
        self._build_ui()
        self._build_tray()

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_state)
        self.timer.start()
        self._refresh_state()

        self.nav.setCurrentRow(0)

    # ------------------------------------------------------------ построение

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_sidebar(), 0)
        separator = QFrame()
        separator.setObjectName("VLine")
        separator.setFixedWidth(1)
        body.addWidget(separator, 0)
        body.addLayout(self._build_pages(), 1)
        root.addLayout(body, 1)

    def _build_sidebar(self) -> QWidget:
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        layout = QVBoxLayout(self.sidebar)
        layout.setContentsMargins(4, 16, 14, 14)
        layout.setSpacing(8)

        # --- бренд: название с подписью либо одна иконка в свёрнутом виде ---
        head = QHBoxLayout()
        head.setSpacing(8)

        self.brand_icon = QLabel()
        self.brand_icon.setObjectName("BrandIcon")
        self.brand_icon.setFixedSize(34, 34)
        self.brand_icon.setAlignment(Qt.AlignCenter)
        self._set_brand_pixmap()
        self.brand_icon.setVisible(self._collapsed)
        head.addWidget(self.brand_icon, 0, Qt.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.brand_title = QLabel(tr("app.name"))
        self.brand_title.setObjectName("BrandTitle")
        titles.addWidget(self.brand_title)
        self.brand_sub = QLabel(tr("app.subtitle"))
        self.brand_sub.setObjectName("BrandSub")
        self.brand_sub.setWordWrap(True)
        titles.addWidget(self.brand_sub)
        head.addLayout(titles, 1)

        self.sidebar_toggle = IconButton(
            "chevron-left" if not self._collapsed else "chevron-right",
            "",
            "iconButton",
            16,
            tooltip=tr("sidebar.collapse") if not self._collapsed else tr("sidebar.expand"),
        )
        self.sidebar_toggle.setObjectName("SidebarToggle")
        self.sidebar_toggle.setFixedSize(30, 30)
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        head.addWidget(self.sidebar_toggle, 0, Qt.AlignTop)
        layout.addLayout(head)

        layout.addSpacing(10)

        # --- меню ---
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setSpacing(2)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for key in NAV_ITEMS:
            item = QListWidgetItem(tr(key))
            item.setData(Qt.UserRole, key)
            item.setData(Qt.UserRole + 1, NAV_ICONS.get(key, "info"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setSizeHint(QSize(0, 52))
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav, 0)

        layout.addStretch(1)

        # --- состояние запретов в подвале боковой панели ---
        self.state_pill = StatusPill()
        self.state_pill.setMinimumHeight(28)
        layout.addWidget(self.state_pill, 0)

        self._apply_sidebar_mode()
        return self.sidebar

    def _set_brand_pixmap(self) -> None:
        """Иконка программы для свёрнутого меню (если файл нашёлся)."""
        pixmap = app_pixmap(256)
        if pixmap is not None and not pixmap.isNull():
            self.brand_icon.setPixmap(
                pixmap.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.brand_icon.setProperty("has_icon", "yes")
            return
        # иконки нет — оставляем короткую метку ZH
        self.brand_icon.setText("ZH")
        self.brand_icon.setProperty("has_icon", "no")

    def _apply_sidebar_mode(self) -> None:
        """Переключает боковую панель между подписями и одними иконками."""
        collapsed = self._collapsed
        self.sidebar.setFixedWidth(
            SIDEBAR_WIDTH_COLLAPSED if collapsed else SIDEBAR_WIDTH
        )
        self.sidebar.layout().setContentsMargins(
            4 if collapsed else 4, 16, 4 if collapsed else 14, 14
        )
        self.brand_icon.setVisible(collapsed)
        self.brand_title.setVisible(not collapsed)
        self.brand_sub.setVisible(not collapsed)
        self.sidebar_toggle.setIcon(
            icons.get_icon(
                "chevron-right" if collapsed else "chevron-left",
                theme.PALETTE["muted"],
                16,
            )
        )
        self.sidebar_toggle.setToolTip(
            tr("sidebar.expand") if collapsed else tr("sidebar.collapse")
        )

        self.nav.setIconSize(QSize(20, 20) if collapsed else QSize(0, 0))
        for index in range(self.nav.count()):
            item = self.nav.item(index)
            key = item.data(Qt.UserRole)
            if collapsed:
                item.setIcon(
                    icons.get_icon(
                        item.data(Qt.UserRole + 1) or "info",
                        theme.PALETTE["muted"],
                        20,
                    )
                )
                item.setText("")
                item.setSizeHint(QSize(0, 48))
            else:
                item.setIcon(QIcon())
                item.setText(tr(key))
                item.setSizeHint(QSize(0, 52))
        self._fit_nav_height()

        # в свёрнутом виде статус — короткий: 2/2 или STOP
        self.state_pill.setMinimumWidth(0 if collapsed else 104)
        self.state_pill.setMinimumHeight(28)
        self.state_pill.setProperty("compact", "yes" if collapsed else "no")
        self.state_pill.style().unpolish(self.state_pill)
        self.state_pill.style().polish(self.state_pill)
        # страницы могут быть ещё не построены (боковая панель собирается первой)
        if hasattr(self, "home_page"):
            self._refresh_state()

    def toggle_sidebar(self) -> None:
        """Свернуть/развернуть боковое меню (значение запоминается)."""
        self._collapsed = not self._collapsed
        self.ctx.config.general.sidebar_collapsed = self._collapsed
        self.ctx.save_config()
        self._apply_sidebar_mode()

    def _fit_nav_height(self) -> None:
        """Подбирает высоту меню так, чтобы все пункты видны без прокрутки.

        Полоса прокрутки в меню не нужна: пунктов всего четыре, а случайный
        поворот колеса мыши над меню не должен ничего «пролистывать».
        """
        nav = self.nav
        count = nav.count()
        if not count:
            return
        row_height = max(nav.sizeHintForRow(i) for i in range(count))
        fallback = row_height * count + nav.spacing() * (count - 1) + 4
        nav.setFixedHeight(fallback)
        # Стиль добавляет пунктам отступы и рамку, поэтому расчёт выходит чуть
        # меньше нужного. Когда меню разложено, измеряем последний пункт и
        # дотягиваем высоту — иначе появилась бы полоса прокрутки.
        QTimer.singleShot(0, self._grow_nav_height)

    def _grow_nav_height(self) -> None:
        nav = self.nav
        count = nav.count()
        if not count:
            return
        last = nav.visualRect(nav.model().index(count - 1, 0))
        if last.isValid():
            nav.setFixedHeight(max(nav.height(), last.bottom() + 1 + nav.spacing()))
        QApplication.processEvents()
        guard = 0
        while nav.verticalScrollBar().maximum() > 0 and guard < 40:
            nav.setFixedHeight(nav.height() + nav.verticalScrollBar().maximum() + 2)
            QApplication.processEvents()
            guard += 1

    def _build_pages(self) -> QVBoxLayout:
        right = QVBoxLayout()
        right.setSpacing(0)
        self.stack = QStackedWidget()
        self.home_page = HomePage(self.ctx)
        self.components_page = ComponentsPage(self.ctx)
        self.diagnostics_page = DiagnosticsPage(self.ctx)
        self.settings_page = SettingsPage(self.ctx)
        for page in (
            self.home_page,
            self.components_page,
            self.diagnostics_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)
        right.addWidget(self.stack, 1)

        self.home_page.goto_components.connect(self._open_component)
        self.home_page.goto_settings.connect(self.show_settings)
        self.settings_page.settings_applied.connect(self._on_settings_applied)
        self.diagnostics_page.busy_changed.connect(self._on_diagnostics_busy)
        self.ctx.updater.installed.connect(self._on_component_installed)
        return right

    def _build_tray(self) -> None:
        self.tray = TrayManager(self, self.ctx)

    # ------------------------------------------------------------ навигация

    def _on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        self._switch_page(row, animate=self._animate)

    def _on_diagnostics_busy(self, busy: bool) -> None:
        """Пока идёт прогон диагностики, со страницы уходить нельзя."""
        self._diagnostics_busy = bool(busy)
        self.nav.setEnabled(not self._diagnostics_busy)
        # во время перебора zapret запущен, поэтому пункт в трее
        # должен стать «Остановить все» — и снова «Запустить все» после
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.refresh()

    def _locked_by_diagnostics(self) -> bool:
        """Уйти со страницы диагностики во время прогона нельзя."""
        return (
            getattr(self, "_diagnostics_busy", False)
            and self.stack.currentIndex() == PAGE_INDEX["nav.diagnostics"]
        )

    def _switch_page(self, index: int, animate: bool = True) -> None:
        if index == self.stack.currentIndex():
            return
        if self._locked_by_diagnostics():
            self.nav.setCurrentRow(self.stack.currentIndex())
            return
        if animate:
            anim.crossfade(self.stack, index)
        else:
            self.stack.setCurrentIndex(index)
        page = self.stack.widget(index)
        if hasattr(page, "on_show"):
            page.on_show()

    def goto_page(self, index: int, animate: bool = True) -> None:
        if index == self.stack.currentIndex():
            page = self.stack.widget(index)
            if hasattr(page, "on_show"):
                page.on_show()
            return
        if self._locked_by_diagnostics():
            return
        self._animate = animate
        self.nav.setCurrentRow(index)

    def show_components(self) -> None:
        self.goto_page(PAGE_INDEX["nav.components"])

    def _open_component(self, key: str) -> None:
        self.goto_page(PAGE_INDEX["nav.components"])
        self.components_page.focus_component(key)

    def show_home(self) -> None:
        self.goto_page(0)

    def show_settings(self) -> None:
        self.goto_page(PAGE_INDEX["nav.settings"])

    def auto_check_updates(self) -> None:
        """Открыть диалог обновлений (по кнопке)."""
        from .update_dialog import UpdateDialog

        dialog = UpdateDialog(self.ctx, parent=self)
        dialog.exec()

    def background_check_updates(self) -> None:
        """Тихая проверка при старте: не блокирует окно, результат — тост."""
        updater = self.ctx.updater
        if getattr(self, "_bg_check_connected", False):
            return
        self._bg_check_connected = True

        def _on_finished(infos: list) -> None:
            # «Доступно обновление» — только про то, что реально установлено.
            # Не установленный компонент это не обновление, а ещё не
            # поставленная программа: про неё расскажет страница
            # «Компоненты», а тост про обновление только путает.
            installed = [info for info in infos if info.installed]
            updates = [info for info in installed if info.update_available]
            if not updates:
                if not installed:
                    # нечего обновлять — молчим, иначе «всё актуально»
                    # звучит странно, когда компонентов нет вообще
                    return
                show_toast(self, tr("upd.up_to_date"), "success", duration=2600)
                return
            names = ", ".join(
                TITLES.get(info.component, info.component) for info in updates
            )
            show_toast(
                self,
                f"{tr('upd.update_available')}: {names}",
                "info",
                action_text=tr("upd.open"),
                action_cb=self.auto_check_updates,
                duration=9000,
            )

        updater.check_finished.connect(_on_finished)
        updater.check_failed.connect(
            lambda message: show_toast(self, f"{tr('upd.github_error')}: {message}", "error", duration=7000)
        )
        updater.check_all()

    # ------------------------------------------------------------ состояние

    def _refresh_state(self) -> None:
        self.home_page.refresh_status()
        self.components_page.refresh_status()
        self.diagnostics_page.refresh_status()
        # пункт меню в трее: «Запустить всё» ↔ «Остановить всё»
        if getattr(self, "tray", None) is not None:
            self.tray.refresh()

        running = self.ctx.any_running()
        installed = self.ctx.components_installed()
        collapsed = getattr(self, "_collapsed", False)

        if not installed:
            self.state_pill.set_status("stopped", tr("common.not_installed"))
        elif running:
            active = sum(1 for c in (self.ctx.zapret, self.ctx.tgws) if c.is_running())
            self.state_pill.set_status(
                "running",
                f"{active}/2" if collapsed else tr("dash.summary", active=active, total=2),
            )
        else:
            # в свёрнутом виде — короткая метка, без слов
            self.state_pill.set_status(
                "stopped", "STOP" if collapsed else tr("common.stopped")
            )

        # права администратора показываем подсказкой у названия программы
        admin = win32.is_admin()
        self.brand_icon.setToolTip(
            f"{tr('status.admin')}: "
            f"{tr('status.admin_yes') if admin else tr('status.admin_no')}"
        )

    def _on_component_installed(self, component: str, version: str) -> None:
        show_toast(self, f"{component} → {version}", "success")
        self.tray.notify(tr("app.name"), f"{component} → {version}")

    def _on_settings_applied(self) -> None:
        if self.ctx.config.general.language != self.language:
            self._rebuild_window()

    def _rebuild_window(self) -> None:
        from ..i18n import set_language

        was_visible = self.isVisible()
        try:
            self.tray.icon.hide()
        except Exception:
            pass
        self.close()
        self.deleteLater()
        set_language(self.ctx.config.general.language)
        window = MainWindow(self.ctx)
        if was_visible:
            window.show()
        app = QApplication.instance()
        if app is not None:
            setattr(app, "main_window", window)

    # ------------------------------------------------------------ события

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_toasts()

    def _reposition_toasts(self) -> None:
        for toast in getattr(self, "_toasts", []):
            if hasattr(toast, "_reposition"):
                toast._reposition()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.ctx.config.general.minimize_to_tray and self.tray.icon.isVisible():
            self.hide()
            self.tray.notify(tr("app.name"), tr("tray.hint"))
            event.ignore()
            return
        self._confirm_quit(event)

    def _confirm_quit(self, event: QCloseEvent) -> None:
        # установщик закрывает нас через WM_CLOSE: не спрашиваем «Выйти?»,
        # иначе обновление встанет на модальном окне
        if self.ctx.any_running() and not win32.quit_requested():
            from PySide6.QtWidgets import QMessageBox

            answer = QMessageBox.question(
                self,
                tr("app.name"),
                tr("quit.confirm"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.ctx.shutdown()
        event.accept()

    def quit(self) -> None:
        self.ctx.shutdown()
        win32.clear_quit_request()
        QApplication.quit()

    def apply_language(self, language: str) -> None:
        from ..i18n import set_language

        set_language(language)
