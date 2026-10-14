"""Zapret Hub — единый интерфейс управления zapret-discord-youtube и TG WS Proxy."""

#: версия программы. Её же сравниваем с тегом релиза на GitHub, поэтому
#: правится только здесь (и в installer/ZapretHub.iss для сборки установщика).
__version__ = "1.0.1"

#: репозиторий, откуда программа обновляет себя и компоненты
GITHUB_REPO = "kudasai012/ZapretHub"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
RELEASES_URL = f"{GITHUB_URL}/releases"
