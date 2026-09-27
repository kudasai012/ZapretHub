"""Простая система локализации (RU по умолчанию, EN как альтернатива)."""
from __future__ import annotations

import locale
from typing import Any, Dict

STRINGS: Dict[str, Dict[str, str]] = {
    # ---- общее ----
    "app.name": {"ru": "Zapret Hub", "en": "Zapret Hub"},
    "app.version": {"ru": "Версия", "en": "Version"},
    "about.credit": {
        "ru": "Zapret Hub — надстройка над проектами Flowseal. Вся логика обхода блокировок принадлежит их разработчикам; мы лишь объединяем инструменты в одном окне и управляем ими.",
        "en": "Zapret Hub is a front-end for Flowseal's projects. All bypass logic belongs to their authors; we only combine the tools in one window and manage them.",
    },
    "about.versions": {
        "ru": "Используются: zapret-discord-youtube 1.10.3 и tg-ws-proxy v1.10.4.",
        "en": "Built on: zapret-discord-youtube 1.10.3 and tg-ws-proxy v1.10.4.",
    },
    "app.subtitle": {
        "ru": "Единый пульт управления обходом блокировок",
        "en": "Single control panel for bypass tools",
    },
    "action.start_all": {"ru": "Запустить всё", "en": "Start all"},
    "action.stop_all": {"ru": "Остановить всё", "en": "Stop all"},

    "action.minimize": {"ru": "Свернуть", "en": "Minimize"},
    "action.close": {"ru": "Закрыть", "en": "Close"},
    "sidebar.collapse": {"ru": "Свернуть меню", "en": "Collapse the menu"},
    "sidebar.expand": {"ru": "Развернуть меню", "en": "Expand the menu"},
    "status.all_stopped": {"ru": "Все компоненты остановлены", "en": "All components stopped"},
    "status.some_running": {"ru": "Компоненты работают", "en": "Components running"},
    "quit.confirm": {
        "ru": "Компоненты ещё работают. Остановить их и выйти?",
        "en": "Components are still running. Stop them and quit?",
    },
    "common.start": {"ru": "Запустить", "en": "Start"},
    "common.stop": {"ru": "Остановить", "en": "Stop"},
    "common.restart": {"ru": "Перезапустить", "en": "Restart"},
    "common.apply": {"ru": "Применить", "en": "Apply"},
    "common.save": {"ru": "Сохранить", "en": "Save"},
    "common.cancel": {"ru": "Отмена", "en": "Cancel"},
    "common.close": {"ru": "Закрыть", "en": "Close"},
    "common.refresh": {"ru": "Обновить", "en": "Refresh"},
    "common.open_folder": {"ru": "Открыть папку", "en": "Open folder"},
    "common.copy": {"ru": "Копировать", "en": "Copy"},
    "common.copied": {"ru": "Скопировано", "en": "Copied"},
    "common.status": {"ru": "Статус", "en": "Status"},
    "common.running": {"ru": "Работает", "en": "Running"},
    "common.stopped": {"ru": "Остановлен", "en": "Stopped"},
    "action.toggle": {"ru": "Запустить / остановить", "en": "Start / stop"},
    "action.start": {"ru": "Запустить", "en": "Start"},
    "action.stop": {"ru": "Остановить", "en": "Stop"},
    "home.bypasses": {"ru": "Отдельные обходы", "en": "Individual bypasses"},
    "home.bypass_zapret": {"ru": "Discord / YouTube", "en": "Discord / YouTube"},
    "home.bypass_tgws": {"ru": "Telegram", "en": "Telegram"},
    "home.bypass_zapret_sub": {"ru": "zapret-discord-youtube", "en": "zapret-discord-youtube"},
    "home.bypass_tgws_sub": {"ru": "tg-ws-proxy · MTProto", "en": "tg-ws-proxy · MTProto"},
    "home.badge_game": {"ru": "Game Filter", "en": "Game Filter"},
    "home.badge_game_off": {"ru": "выкл.", "en": "off"},
    "home.badge_game_tcp": {"ru": "TCP", "en": "TCP"},
    "home.badge_game_udp": {"ru": "UDP", "en": "UDP"},
    "home.badge_game_all": {"ru": "TCP+UDP", "en": "TCP+UDP"},
    "home.badge_ipset": {"ru": "IPSet", "en": "IPSet"},
    "home.badge_ipset_loaded": {"ru": "список", "en": "list"},
    "home.badge_ipset_none": {"ru": "выкл.", "en": "off"},
    "home.badge_ipset_any": {"ru": "любые", "en": "any"},
    "home.badge_port": {"ru": "Порт", "en": "Port"},
    "home.badge_dc": {"ru": "DC", "en": "DC"},
    "common.starting": {"ru": "Запуск...", "en": "Starting..."},
    "common.stopping": {"ru": "Остановка...", "en": "Stopping..."},
    "common.crashed": {"ru": "Аварийно завершён", "en": "Crashed"},
    "common.not_installed": {"ru": "Не установлен", "en": "Not installed"},
    "common.unknown": {"ru": "неизвестно", "en": "unknown"},
    "common.uptime": {"ru": "В работе", "en": "Uptime"},
    "common.yes": {"ru": "Да", "en": "Yes"},
    "common.no": {"ru": "Нет", "en": "No"},
    "common.error": {"ru": "Ошибка", "en": "Error"},
    "common.warning": {"ru": "Предупреждение", "en": "Warning"},
    "common.info": {"ru": "Информация", "en": "Information"},
    "common.success": {"ru": "Готово", "en": "Success"},
    "common.loading": {"ru": "Загрузка...", "en": "Loading..."},
    "common.seconds": {"ru": "с", "en": "s"},
    "components.open_settings": {"ru": "Открыть настройки", "en": "Open settings"},
    "components.install_hint": {
        "ru": "Этот обход ещё не скачан. Нажмите «Установить» — Hub возьмёт последнюю версию с GitHub и положит её в components/.",
        "en": "This bypass is not downloaded yet. Press Install and Hub will fetch the latest release from GitHub into components/.",
    },
    "components.install_all": {"ru": "Установить все", "en": "Install all"},

    "state.connected": {"ru": "Подключён", "en": "Connected"},
    "state.off": {"ru": "Выключен", "en": "Off"},
    "state.error": {"ru": "Ошибка", "en": "Error"},
    "state.reconnecting": {"ru": "Переподключение", "en": "Reconnecting"},

    # ---- навигация ----

    # ---- страница компонентов ----
    "components.title": {"ru": "Компоненты", "en": "Components"},
    "components.subtitle": {
        "ru": "Настройки каждого обхода блокировок отдельно",
        "en": "Settings for each bypass separately",
    },
    "nav.sections": {"ru": "Разделы", "en": "Sections"},
    "nav.dashboard": {"ru": "Обзор", "en": "Dashboard"},
    "nav.zapret": {"ru": "Zapret", "en": "Zapret"},
    "nav.tgws": {"ru": "TG WS Proxy", "en": "TG WS Proxy"},
    "nav.settings": {"ru": "Настройки", "en": "Settings"},

    "nav.home": {"ru": "Главная", "en": "Home"},
    "nav.components": {"ru": "Компоненты", "en": "Components"},
    "nav.diagnostics": {"ru": "Диагностика", "en": "Diagnostics"},

    # ---- страница диагностики ----
    "diag.title": {"ru": "Диагностика", "en": "Diagnostics"},
    "diag.subtitle": {
        "ru": "Перебор всех стратегий general*.bat и выбор самой быстрой для вашего соединения",
        "en": "Test every general*.bat strategy and pick the fastest for your connection",
    },
    "diag.not_installed": {
        "ru": "Zapret не установлен — тестировать стратегии нечем. Установите компонент на странице «Компоненты».",
        "en": "Zapret is not installed, so there is nothing to test. Install it on the Components page.",
    },
    "diag.run_title": {"ru": "Автоподбор стратегии", "en": "Auto strategy picker"},
    "diag.run_hint": {
        "ru": "Приложение по очереди запустит каждую стратегию general*.bat и проверит каждый сайт из списка теми же тестами, что и пакет: HEAD-запрос по HTTP/1.1, TLS 1.2 и TLS 1.3, плюс ping. Текущая стратегия будет восстановлена.",
        "en": "The app starts each general*.bat strategy in turn and tests every site from the list the same way the package does: a HEAD request over HTTP/1.1, TLS 1.2 and TLS 1.3, plus ping. Your current strategy is restored afterwards.",
    },
    "diag.start": {"ru": "Протестировать все", "en": "Test all"},
    "diag.stop": {"ru": "Остановить", "en": "Stop"},
    "diag.strategies": {"ru": "Стратегии general*.bat", "en": "general*.bat strategies"},
    "diag.hide_strategies": {"ru": "Скрыть стратегии", "en": "Hide strategies"},
    "diag.now_testing": {
        "ru": "СЕЙЧАС ПРОВЕРЯЕТСЯ",
        "en": "CURRENTLY TESTING",
    },
    "diag.targets_title": {
        "ru": "Проверяемые HTTP и PING",
        "en": "HTTP and PING targets",
    },
    "diag.targets_hint": {
        "ru": "По одной цели на строку. Как в utils/targets.txt пакета: «Имя = https://сайт» — проверяем HTTP/1.1, TLS 1.2, TLS 1.3 и ping; «Имя = PING:адрес» — только ping. Можно и просто «сайт» или «сайт:порт». Если цель не ответила за 10 секунд, остальные её проверки не делаются и считаются «нет ответа». Выше в списке та стратегия, которая открыла больше целей и отвечает быстрее.",
        "en": "One target per line, same as the package's utils/targets.txt: \"Name = https://site\" checks HTTP/1.1, TLS 1.2, TLS 1.3 and ping; \"Name = PING:address\" pings only. A plain \"site\" or \"site:port\" works too. If a target does not answer within 10 seconds, its remaining checks are skipped and counted as no answer. Higher in the list goes the strategy that answered more targets and answered faster.",
    },
    "diag.targets_count": {
        "ru": "Целей: {count} · проверок на стратегию: {checks}",
        "en": "Targets: {count} · checks per strategy: {checks}",
    },
    "diag.targets_empty": {
        "ru": "Список пуст — тестировать нечем. Верните стандартные сайты кнопкой ниже.",
        "en": "The list is empty, there is nothing to test. Restore the default sites with the button below.",
    },
    "diag.targets_reset": {
        "ru": "Стандартные сайты",
        "en": "Default sites",
    },
    "diag.targets_reset_hint": {
        "ru": "Вернуть список сайтов из utils/targets.txt пакета",
        "en": "Restore the site list from the package's utils/targets.txt",
    },
    "diag.targets_restored": {
        "ru": "Список целей взят из utils/targets.txt пакета",
        "en": "Target list taken from the package's utils/targets.txt",
    },
    "diag.best_choice": {
        "ru": "ЛУЧШИЙ ВЫБОР",
        "en": "BEST CHOICE",
    },
    "diag.best_pill": {"ru": "Готово", "en": "Ready"},
    "diag.pick_hint": {
        "ru": "Проверять эту стратегию в общем прогоне",
        "en": "Include this strategy in the full run",
    },
    "diag.pick_all": {
        "ru": "Отметить все стратегии",
        "en": "Select every strategy",
    },
    "diag.pick_none": {
        "ru": "Снять отметки со всех стратегий",
        "en": "Clear every strategy selection",
    },
    "diag.picked_count": {
        "ru": "Отмечено стратегий: {count}",
        "en": "Strategies selected: {count}",
    },
    "diag.nothing_picked": {
        "ru": "Не отмечено ни одной стратегии — отметьте хотя бы одну",
        "en": "No strategy selected — pick at least one",
    },
    "diag.auto_applied": {
        "ru": "По итогам прогона применена стратегия",
        "en": "Strategy applied from the run results",
    },
    "diag.auto_applied_toast": {
        "ru": "Автоматически применена лучшая стратегия: {name} — ответили {percent}% проверок",
        "en": "Best strategy applied automatically: {name} — {percent}% of checks answered",
    },
    "diag.start_count": {
        "ru": "Протестировать · {count}",
        "en": "Test · {count}",
    },
    "diag.start_hint": {
        "ru": "Проверить отмеченные стратегии и применить лучшую",
        "en": "Test the selected strategies and apply the best one",
    },
    "diag.stop_hint": {
        "ru": "Остановить прогон и применить лучшую из проверенных",
        "en": "Stop the run and apply the best of the tested ones",
    },
    "diag.log": {"ru": "Журнал проверки", "en": "Test log"},
    "diag.waiting": {"ru": "Ожидание", "en": "Waiting"},
    "diag.testing": {"ru": "Проверка", "en": "Testing"},
    "diag.done": {"ru": "Готово", "en": "Done"},
    "diag.ok": {"ru": "Успешно", "en": "OK"},
    "diag.targets_covered": {"ru": "Цели", "en": "Targets"},
    "diag.avg": {"ru": "Среднее", "en": "Avg"},
    "diag.fastest": {"ru": "Быстрее всего", "en": "Fastest"},
    "diag.no_access": {"ru": "Нет доступа", "en": "No access"},
    "diag.choose": {"ru": "Выбрать", "en": "Choose"},
    "diag.test_one": {
        "ru": "Протестировать только эту стратегию",
        "en": "Test only this strategy",
    },
    "diag.no_log": {
        "ru": "Эта стратегия ещё не проверялась.",
        "en": "This strategy has not been tested yet.",
    },
    "diag.choose_hint": {"ru": "Сделать эту стратегию текущей", "en": "Make this the current strategy"},
    "diag.row_hint": {
        "ru": "Нажмите, чтобы протестировать только эту стратегию",
        "en": "Click to test only this strategy",
    },
    "diag.started": {"ru": "Запуск автоподбора", "en": "Auto picker started"},
    "diag.stopped": {"ru": "Автоподбор остановлен", "en": "Auto picker stopped"},
    "diag.trying": {"ru": "Проверяю стратегию", "en": "Testing strategy"},
    "diag.start_failed": {"ru": "Не удалось запустить", "en": "Failed to start"},
    "diag.best_found": {"ru": "Лучшая стратегия", "en": "Best strategy"},
    "diag.no_best": {"ru": "Рабочих стратегий не найдено", "en": "No working strategy found"},
    "diag.applied": {"ru": "Стратегия применена", "en": "Strategy applied"},
    "diag.bar_hint": {
        "ru": "График проверок: ответили {percent}% из {count} проверок. "
              "Зелёный — ответ быстрее {slow} мс, жёлтый — медленный ответ, "
              "красный — нет ответа.",
        "en": "Check graph: {percent}% of {count} checks answered. "
              "Green — answered in under {slow} ms, yellow — slow answer, "
              "red — no answer.",
    },
    "diag.chosen": {
        "ru": "Стратегия «{name}» выбрана — применится при следующем запуске",
        "en": "Strategy \u00ab{name}\u00bb chosen — it will apply on the next start",
    },
    "diag.chosen_restarted": {
        "ru": "Стратегия «{name}» выбрана и перезапущена",
        "en": "Strategy \u00ab{name}\u00bb chosen and restarted",
    },
    "diag.chosen_error": {
        "ru": "Стратегия «{name}» выбрана, но перезапустить не удалось: {error}",
        "en": "Strategy \u00ab{name}\u00bb chosen, but the restart failed: {error}",
    },
    "diag.best_toast": {
        "ru": "Лучшая стратегия: {name} — быстрых ответов {percent}%",
        "en": "Best strategy: {name} — {percent}% fast answers",
    },

    # ---- статусная строка / трей ----
    "tray.show": {"ru": "Открыть Zapret Hub", "en": "Open Zapret Hub"},
    "tray.hide": {"ru": "Свернуть в трей", "en": "Hide to tray"},
    "tray.start_all": {"ru": "Запустить всё", "en": "Start all"},
    "tray.stop_all": {"ru": "Остановить всё", "en": "Stop all"},
    "tray.quit": {"ru": "Выход", "en": "Quit"},
    "tray.hint": {"ru": "Приложение свёрнуто в трей", "en": "Application minimized to tray"},
    "status.admin": {"ru": "Права администратора", "en": "Administrator rights"},
    "status.admin_short": {"ru": "Админ", "en": "Admin"},
    "status.admin_yes": {"ru": "есть", "en": "granted"},
    "status.admin_no": {"ru": "нет (нужны для Zapret)", "en": "missing (required for Zapret)"},
    "status.admin_relaunch": {
        "ru": "Для работы Zapret нужны права администратора. Перезапустить программу от имени администратора?",
        "en": "Zapret requires administrator rights. Restart the app as administrator?",
    },
    "status.admin_restarting": {
        "ru": "Перезапуск от имени администратора...",
        "en": "Restarting as administrator...",
    },
    "status.windows_only": {
        "ru": "Этот компонент работает только в Windows",
        "en": "This component only works on Windows",
    },

    # ---- дашборд ----
    "dash.title": {"ru": "Обзор", "en": "Dashboard"},
    "dash.subtitle": {
        "ru": "Единая точка управления zapret-discord-youtube и TG WS Proxy",
        "en": "Single control point for zapret-discord-youtube and TG WS Proxy",
    },
    "dash.master_title": {"ru": "Общий запуск", "en": "Master control"},
    "dash.not_installed_title": {"ru": "Компоненты не установлены", "en": "Components are not installed"},
    "dash.not_installed_text": {
        "ru": "Компоненты не установлены. Нажмите иконку обновления в панели компонента на странице «Компоненты», чтобы скачать zapret-discord-youtube и TG WS Proxy с GitHub.",
        "en": "Components are not installed. Click the update icon in a component panel on the Components page to download zapret-discord-youtube and TG WS Proxy from GitHub.",
    },
    "dash.goto_updates": {"ru": "Перейти к обновлениям", "en": "Go to updates"},
    "dash.quick_actions": {"ru": "Быстрые действия", "en": "Quick actions"},

    "dash.statuses": {"ru": "Состояние запретов", "en": "Bypass status"},
    "dash.row_open_settings": {"ru": "открыть настройки", "en": "open settings"},
    "dash.connect_error": {
        "ru": "Не подключилось",
        "en": "Could not connect",
    },
    "dash.summary": {
        "ru": "Активно {active} из {total}",
        "en": "{active} of {total} active",
    },
    "dash.goto_components": {
        "ru": "Открыть настройки компонентов",
        "en": "Open component settings",
    },
    "dash.open_components": {"ru": "Папка компонентов", "en": "Components folder"},
    "dash.open_logs": {"ru": "Папка логов", "en": "Logs folder"},
    "dash.not_installed_hint": {
        "ru": "Откройте «Компоненты» и нажмите иконку обновления у нужного запрета.",
        "en": "Open Components and click the update icon of the bypass you need.",
    },
    "dash.autostart_off": {
        "ru": "Автозапуск выключен. Включите его в разделе «Настройки».",
        "en": "Autostart is disabled. Enable it in Settings.",
    },

    # ---- zapret ----
    "zapret.title": {"ru": "Zapret (обход блокировок Discord/YouTube)", "en": "Zapret (Discord/YouTube bypass)"},
    "zapret.component": {"ru": "Компонент", "en": "Component"},
    "zapret.strategy": {"ru": "Стратегия", "en": "Strategy"},
    "zapret.strategy_hint": {
        "ru": "Просто выберите .bat-файл стратегии из пакета zapret-discord-youtube — нашему приложению останется лишь запустить её как есть. Если запрет работает, он перезапустится с новой стратегией.",
        "en": "Just pick a .bat strategy file from the zapret-discord-youtube package — our app launches it as is. If the bypass is running, it restarts with the new strategy.",
    },
    "zapret.game_filter": {"ru": "Game Filter (порты игр)", "en": "Game Filter (game ports)"},
    "zapret.game_mode": {"ru": "Режим", "en": "Mode"},
    "zapret.game_disabled": {"ru": "Выключен", "en": "Disabled"},
    "zapret.game_all": {"ru": "TCP и UDP", "en": "TCP and UDP"},
    "zapret.game_tcp": {"ru": "Только TCP", "en": "TCP only"},
    "zapret.game_udp": {"ru": "Только UDP", "en": "UDP only"},
    "zapret.game_tcp_range": {"ru": "TCP порты", "en": "TCP ports"},
    "zapret.game_udp_range": {"ru": "UDP порты", "en": "UDP ports"},
    "zapret.ipset": {"ru": "IPSet-фильтр", "en": "IPSet filter"},
    "zapret.ipset_loaded": {"ru": "Загружен (список IP)", "en": "Loaded (IP list)"},
    "zapret.ipset_none": {"ru": "Отключён (none)", "en": "Disabled (none)"},
    "zapret.ipset_any": {"ru": "Любые IP (any)", "en": "Any IP (any)"},
    "zapret.asn_collect": {"ru": "Собрать IP по ASN", "en": "Collect IPs by ASN"},
    "zapret.asn_stop": {"ru": "Остановить сбор", "en": "Stop collecting"},
    "zapret.asn_hint": {
        "ru": "Запрашивает у RIPE Stat все префиксы провайдеров из списка ASN и пишет их в lists/ipset-all.txt",
        "en": "Queries RIPE Stat for all prefixes of the ASN providers and writes them to lists/ipset-all.txt",
    },
    "zapret.asn_done": {
        "ru": "Готово: IPv4 {v4}, IPv6 {v6} сетей записано в ipset-all.txt",
        "en": "Done: IPv4 {v4}, IPv6 {v6} networks written to ipset-all.txt",
    },
    "zapret.ipset_update": {"ru": "Обновить список IP", "en": "Update IP list"},
    "zapret.user_lists": {"ru": "Списки адресов", "en": "Address lists"},
    "zapret.user_lists_hint": {
        "ru": "Все .txt-файлы из lists/ — общие и пользовательские. Пользовательские (*-user.txt) не перезаписываются при обновлении компонента.",
        "en": "All .txt files from lists/ — both shared and user ones. User files (*-user.txt) survive component updates.",
    },
    "zapret.list_saved": {"ru": "Список сохранён", "en": "List saved"},
    "zapret.list_saved_toast": {
        "ru": "Список «{name}» сохранён",
        "en": "List \u00ab{name}\u00bb saved",
    },
    "zapret.strategy_applied": {
        "ru": "Стратегия «{name}» выбрана",
        "en": "Strategy \u00ab{name}\u00bb selected",
    },
    "zapret.game_applied": {
        "ru": "Game Filter применён: {mode}",
        "en": "Game Filter applied: {mode}",
    },
    "zapret.game_applied_error": {
        "ru": "Не удалось применить Game Filter",
        "en": "Could not apply Game Filter",
    },
    "zapret.ipset_applied": {
        "ru": "Режим IPSet применён: {mode}",
        "en": "IPSet mode applied: {mode}",
    },
    "zapret.ipset_applied_error": {
        "ru": "Не удалось применить режим IPSet",
        "en": "Could not apply IPSet mode",
    },
    "zapret.service_conflict": {
        "ru": "Обнаружена служба Windows «zapret». Она мешает запуску в режиме нашего приложения. Удалить службу?",
        "en": "Windows service 'zapret' detected. It prevents running inside our app. Remove the service?",
    },
    "zapret.service_removed": {"ru": "Служба «zapret» удалена", "en": "Service 'zapret' removed"},
    "zapret.service_remove": {"ru": "Удалить службу", "en": "Remove service"},
    "zapret.service_remove_confirm": {
        "ru": "Удалить службу Windows «zapret»? Запреты будут запускаться нашим приложением.",
        "en": "Remove the Windows 'zapret' service? Bypass will be managed by this app.",
    },
    "zapret.external_winws": {
        "ru": "Обнаружен сторонний процесс winws.exe — остановите его, иначе будет конфликт.",
        "en": "A third-party winws.exe process is running — stop it to avoid conflicts.",
    },
    "zapret.restart_needed": {
        "ru": "Изменения вступят в силу после перезапуска",
        "en": "Changes take effect after restart",
    },
    "zapret.no_strategies": {
        "ru": "Стратегии не найдены. Установите компонент иконкой обновления в его панели.",
        "en": "No strategies found. Install the component with the update icon in its panel.",
    },

    # ---- tgws ----
    "tgws.title": {"ru": "TG WS Proxy (MTProto-прокси для Telegram)", "en": "TG WS Proxy (MTProto proxy for Telegram)"},
    "tgws.connection": {"ru": "Подключение", "en": "Connection"},
    "tgws.host": {"ru": "Адрес", "en": "Host"},
    "tgws.port": {"ru": "Порт", "en": "Port"},
    "tgws.secret": {"ru": "Secret", "en": "Secret"},
    "tgws.generate": {"ru": "Сгенерировать", "en": "Generate"},
    "tgws.dc_ip": {"ru": "DC IP (по одному в строке)", "en": "DC IP (one per line)"},
    "tgws.advanced": {"ru": "Дополнительно", "en": "Advanced"},
    "tgws.buf_kb": {"ru": "Буфер (КБ)", "en": "Buffer (KB)"},
    "tgws.pool_size": {"ru": "Пулов", "en": "Pool size"},
    "tgws.verbose": {"ru": "Подробные логи", "en": "Verbose logging"},
    "tgws.cfproxy": {"ru": "Резерв через CfProxy", "en": "Fallback via CfProxy"},
    "tgws.force_test_dc": {"ru": "Тестовые DC", "en": "Test DCs"},
    "tgws.no_secure": {"ru": "Отключить TLS (no_secure)", "en": "Disable TLS (no_secure)"},
    "tgws.its_check_updates": {"ru": "Проверять обновления (внутри TgWsProxy)", "en": "Check updates (inside TgWsProxy)"},
    "tgws.link": {"ru": "Ссылка для Telegram", "en": "Telegram link"},
    "tgws.copy_link": {"ru": "Копировать ссылку", "en": "Copy link"},
    "tgws.link_copied": {
        "ru": "Ссылка для Telegram скопирована",
        "en": "Telegram link copied",
    },
    "tgws.secret_generated": {
        "ru": "Новый secret сгенерирован",
        "en": "New secret generated",
    },
    "tgws.open_tg": {"ru": "Открыть в Telegram", "en": "Open in Telegram"},
    "tgws.manual_hint": {
        "ru": "Или вручную: Telegram → Настройки → Продвинутые → Тип подключения → Прокси → MTProto.",
        "en": "Or manually: Telegram → Settings → Advanced → Connection type → Proxy → MTProto.",
    },
    "tgws.config_applied": {"ru": "Конфигурация сохранена", "en": "Configuration saved"},
    "tgws.port_invalid": {"ru": "Некорректный порт (1–65535)", "en": "Invalid port (1-65535)"},

    # ---- обновления ----
    "upd.title": {"ru": "Обновления компонентов", "en": "Component updates"},

    "upd.dialog_title": {"ru": "Обновление компонентов", "en": "Update components"},
    "upd.check_all": {"ru": "Проверить обновления", "en": "Check for updates"},
    "upd.done": {
        "ru": "Все выбранные компоненты обновлены",
        "en": "All selected components updated",
    },
    "upd.installed": {"ru": "Установлено", "en": "Installed"},
    "upd.latest": {"ru": "Доступно", "en": "Available"},
    "upd.action": {"ru": "Действие", "en": "Action"},
    "upd.component": {"ru": "Компонент", "en": "Component"},
    "upd.check": {"ru": "Проверить обновления", "en": "Check for updates"},
    "upd.open": {"ru": "Открыть", "en": "Open"},
    "upd.check_short": {"ru": "Проверить", "en": "Check"},
    "upd.install_short": {"ru": "Установить", "en": "Install"},
    "upd.update_short": {"ru": "Обновить", "en": "Update"},
    "upd.checking": {"ru": "Проверка...", "en": "Checking..."},
    "upd.check_timeout": {
        "ru": "GitHub не ответил за 15 секунд. Проверьте соединение или укажите прокси — и нажмите «Проверить» снова.",
        "en": "GitHub did not answer within 15 seconds. Check your connection or set a proxy, then press Check again.",
    },
    "upd.partial_error": {
        "ru": "Не удалось проверить часть компонентов (см. статусы ниже).",
        "en": "Some components could not be checked (see statuses below).",
    },
    "upd.network_hint": {
        "ru": "Если GitHub недоступен из вашей сети, укажите прокси (http/socks5) в поле выше — он сохранится в настройках.",
        "en": "If GitHub is unreachable from your network, set a proxy (http/socks5) in the field above — it is saved to settings.",
    },
    "upd.update": {"ru": "Обновить", "en": "Update"},
    "upd.up_to_date": {"ru": "Актуальная версия", "en": "Up to date"},
    "upd.not_checked": {"ru": "Не проверено", "en": "Not checked"},
    "upd.update_available": {"ru": "Доступно обновление", "en": "Update available"},
    "upd.not_installed": {"ru": "Не установлен", "en": "Not installed"},
    "upd.install": {"ru": "Установить", "en": "Install"},
    "upd.changelog": {"ru": "Что нового", "en": "Changelog"},
    "upd.auto_check": {"ru": "Автоматически проверять обновления", "en": "Check for updates automatically"},
    "upd.interval": {"ru": "Интервал проверки (часы)", "en": "Check interval (hours)"},
    "upd.proxy": {"ru": "Прокси для GitHub (http/socks5)", "en": "Proxy for GitHub (http/socks5)"},
    "upd.downloading": {"ru": "Скачивание", "en": "Downloading"},
    "upd.installing": {"ru": "Установка...", "en": "Installing..."},
    "upd.updated": {"ru": "обновлён до", "en": "updated to"},
    "upd.update_failed": {"ru": "Ошибка обновления", "en": "Update failed"},
    "upd.backups": {"ru": "Резервные копии", "en": "Backups"},
    "upd.open_backups": {"ru": "Открыть папку резервных копий", "en": "Open backups folder"},
    "upd.user_data_kept": {
        "ru": "Пользовательские списки и настройки сохранены.",
        "en": "User lists and settings were preserved.",
    },
    "upd.need_install_first": {
        "ru": "Сначала установите компонент.",
        "en": "Install the component first.",
    },
    "upd.github_error": {
        "ru": "Не удалось связаться с GitHub. Проверьте соединение или задайте прокси в настройках.",
        "en": "Could not reach GitHub. Check your connection or set a proxy in settings.",
    },

    # ---- настройки ----
    "set.title": {"ru": "Настройки", "en": "Settings"},
    "set.general": {"ru": "Общие", "en": "General"},
    "set.language": {"ru": "Язык интерфейса", "en": "Interface language"},
    "set.minimize_to_tray": {"ru": "Сворачивать в трей вместо закрытия", "en": "Minimize to tray instead of closing"},
    "set.start_minimized": {"ru": "Запускать свёрнутым", "en": "Start minimized"},
    "set.check_on_start": {"ru": "Проверять обновления при запуске", "en": "Check updates on startup"},
    "set.autostart": {"ru": "Автозапуск", "en": "Autostart"},
    "set.autostart_enable": {"ru": "Запускать Zapret Hub при входе в Windows", "en": "Start Zapret Hub on Windows login"},
    "set.autostart_zapret": {"ru": "Вместе с программой запускать Zapret", "en": "Start Zapret with the app"},
    "set.autostart_tgws": {"ru": "Вместе с программой запускать TG WS Proxy", "en": "Start TG WS Proxy with the app"},
    "set.autostart_delay": {"ru": "Задержка запуска компонентов (сек)", "en": "Component start delay (sec)"},
    "set.autostart_elevated": {
        "ru": "Запускать от имени администратора (необходимо для Zapret)",
        "en": "Run as administrator (required for Zapret)",
    },
    "set.autostart_hint": {
        "ru": "Автозапуск добавляет запись в реестр (HKCU\\...\\Run) с параметром «--tray»: программа стартует свёрнутой в трей и поднимает компоненты.",
        "en": "Autostart adds a registry entry (HKCU\\...\\Run) with '--tray': the app starts minimized to tray and brings up the components.",
    },
    "set.autostart_applied": {"ru": "Настройки автозапуска сохранены", "en": "Autostart settings saved"},
    "set.autostart_registry_error": {
        "ru": "Не удалось изменить запись автозапуска в реестре",
        "en": "Failed to change the autostart registry entry",
    },
    "set.paths": {"ru": "Расположение", "en": "Locations"},
    "set.components_dir": {"ru": "Папка компонентов", "en": "Components folder"},
    "set.data_dir": {"ru": "Папка данных", "en": "Data folder"},
    "set.mode_installed": {
        "ru": "Установленный режим: данные лежат в профиле пользователя, "
              "папка программы остаётся неизменяемой.",
        "en": "Installed mode: data lives in the user profile, "
              "the program folder stays read-only.",
    },
    "set.mode_portable": {
        "ru": "Портабельный режим: данные лежат рядом с программой "
              "(рядом найден файл portable.txt).",
        "en": "Portable mode: data lives next to the program "
              "(a portable.txt file was found beside it).",
    },
    "set.about": {"ru": "О программе", "en": "About"},
    "set.settings_saved": {"ru": "Настройки сохранены", "en": "Settings saved"},

    # ---- логи ----
    "log.title": {"ru": "Журнал", "en": "Log"},
    "log.clear": {"ru": "Очистить", "en": "Clear"},
    "log.save": {"ru": "Сохранить как...", "en": "Save as..."},
    "log.autoscroll": {"ru": "Автопрокрутка", "en": "Auto-scroll"},
    "log.open_file": {"ru": "Открыть файл лога", "en": "Open log file"},
    "log.empty": {"ru": "Записей пока нет", "en": "No entries yet"},
}

_current_lang = "ru"


def detect_language() -> str:
    try:
        loc = locale.getdefaultlocale()[0] or ""
    except Exception:
        loc = ""
    return "ru" if loc.lower().startswith("ru") else "en"


def set_language(lang: str) -> None:
    global _current_lang
    _current_lang = lang if lang in ("ru", "en") else "ru"


def current_language() -> str:
    return _current_lang


def tr(key: str, **kwargs: Any) -> str:
    entry = STRINGS.get(key)
    if not entry:
        return key
    text = entry.get(_current_lang) or entry.get("ru") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text
