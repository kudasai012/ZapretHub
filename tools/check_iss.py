"""Статическая проверка installer/ZapretHub.iss без Inno Setup.

Ловит то, из-за чего ISCC падает чаще всего:
  * отсутствующие файлы в [Files]/[Icons]/[Setup];
  * ссылки {cm:...} на необъявленные сообщения;
  * непарные begin/end и незакрытые строки в [Code];
  * неизвестные директивы [Setup].
Запуск:  python tools/check_iss.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISS = ROOT / "installer" / "ZapretHub.iss"

# стандартные сообщения Inno Setup, которые можно использовать в {cm:...}
STANDARD_CM = {
    "CreateDesktopIcon", "AdditionalIcons", "LaunchProgram", "UninstallProgram",
    "SelectStartMenuFolderDesc", "SelectDirDesc", "SelectDirLabel3",
    "ReadyMemoTasks", "ConfirmUninstall", "UninstalledAll", "UninstalledMost",
    "NoIconsDesc", "CreateQuickLaunchIcon", "ReadyMemoAssistants",
}

KNOWN_SETUP = {
    "AppId", "AppName", "AppVersion", "AppVerName", "AppPublisher",
    "VersionInfoVersion", "VersionInfoCompany", "VersionInfoDescription",
    "VersionInfoProductName", "PrivilegesRequired", "ArchitecturesAllowed",
    "ArchitecturesInstallIn64BitMode", "MinVersion", "DefaultDirName",
    "DefaultGroupName", "DisableDirPage", "DisableProgramGroupPage",
    "AllowNoIcons", "UsePreviousPrivileges", "ShowLanguageDialog",
    "UsePreviousLanguage", "UninstallDisplayName", "UninstallDisplayIcon",
    "OutputDir", "OutputBaseFilename", "SetupIconFile", "WizardImageFile",
    "WizardSmallImageFile", "Compression", "SolidCompression",
    "LZMANumBlockThreads", "WizardStyle", "CloseApplications",
    "RestartApplications", "AppMutex", "LicenseFile", "InfoBeforeFile",
    "AppComments", "AppContact", "AppSupportURL", "AppUpdatesURL",
    "DefaultUserInfoName", "DefaultUserInfoOrg", "Uninstallable",
    "CreateUninstallRegKey", "UninstallLogMode", "UpdateUninstallLogSize",
    "ChangesAssociations", "ChangesEnvironment", "CloseApplicationsFilter",
    "RestartIfNeededByRun", "AppMutex", "UsePreviousAppDir",
    "PrivilegesRequiredOverridesAllowed", "SignedUninstaller",
    "SignedUninstallerDir", "OutputManifestFile", "SourceDir", "AllowCancelDuringInstall",
    "AllowNoIcons", "AlwaysRestart", "AppReadmeFile", "AppSupportPhone",
    "DisableFinishedPage", "DisableReadyMemo", "DisableWelcomePage",
    "ExtraDiskSpaceRequired", "InternalCompressLevel", "LanguageDetectionMethod",
    "MergeDuplicateFiles", "MissingMessages", "MissingRunOnceIdsWarning",
    "OpenBrowserAfterSetup", "Output", "Password", "ReserveBytes",
    "RestartApplications", "SetupLogging", "ShowComponentSizes",
    "ShowTasksTreeLines", "TimeStampRounding", "TimeStampsInUTC",
    "TouchDate", "TouchTime", "UninstallDisplaySize", "UninstallFilesDir",
    "UninstallRestartComputer", "UseSetupLdr", "VersionInfoCopyright",
    "VersionInfoTextVersion", "VersionInfoProductVersion", "WizardBackColor",
    "WizardImageBackColor", "WizardImageStretch", "WindowResizable",
    "WindowShowCaption", "WindowStartMaximized", "WindowVisible",
    "WindowWidth", "WindowHeight", "DirExistsWarning", "DisableDirPage",
    "UsedUserAreasWarning", "PrivilegesRequired", "AppendDefaultDirName",
    "AppendDefaultGroupName", "EnableDirDoesntExistWarning",
}

KNOWN_DIRS_FLAGS = {"uninsalwaysuninstall", "uninsneveruninstall", "deleteafterinstall"}
KNOWN_FILES_FLAGS = {
    "ignoreversion", "overwritereadonly", "promptifolder", "dontcopy",
    "uninsneveruninstall", "restartreplace", "deleteafterinstall",
    "regserver", "regtypelib", "restartreplaceuninstall", "sharedfile",
    "isreadme", "ishidden", "uninsremovereadonly", "replacesameversion",
    "allowunsafefiles", "nocompression", "skipifsourcedoesntexist",
    "external", "solidbreak", "setntfscompression", "dontverifychecksum",
}
KNOWN_TASKS_FLAGS = {
    "checkedonce", "checked", "unchecked", "dontinheritcheck", "exclusive",
    "restart", "checkedoncetrue", "hidden", "showcheckbox",
}

errors: list[str] = []
warnings: list[str] = []


def _iss_path(raw: str) -> Path:
    """Путь из .iss: обратные слэши Windows -> разделитель текущей ОС."""
    cleaned = raw.strip().strip('"')
    cleaned = cleaned.replace("\\", "/")
    return (ISS.parent / cleaned).resolve()


def _exists(raw: str) -> bool:
    return _iss_path(raw).exists()


def _split_args(text: str) -> list[str]:
    """Делит аргументы вызова по запятым, не заглядывая в строковые литералы."""
    args: list[str] = []
    buf: list[str] = []
    in_str = False
    in_comment = False
    for ch in text:
        if ch == "'" and not in_comment:
            in_str = not in_str
            buf.append(ch)
            continue
        if ch == "{" and not in_str:
            in_comment = True
            continue
        if ch == "}" and in_comment:
            in_comment = False
            continue
        if in_comment:
            continue
        if ch == "," and not in_str:
            args.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def main() -> int:
    errors.clear()
    warnings.clear()
    if not ISS.exists():
        print(f"нет файла {ISS}")
        return 1
    raw = ISS.read_text(encoding="utf-8")
    # комментарии { ... } и ; в начале строки
    lines = raw.splitlines()

    # ---- разбор секций ----
    sections: dict[str, list[tuple[int, str]]] = {}
    current = None
    for n, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(';'):
            continue
        m = re.match(r"^\[([A-Za-z]+)\]$", stripped)
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        sections[current].append((n, line))

    if "Setup" not in sections:
        err("нет секции [Setup]")

    # ---- [Setup]: известные директивы ----
    for n, line in sections.get("Setup", []):
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if "=" not in stripped:
            err(f"[Setup] строка {n}: нет '=' — {stripped[:60]}")
            continue
        key = stripped.split("=", 1)[0].strip()
        if key not in KNOWN_SETUP:
            warn(f"[Setup] строка {n}: незнакомая директива '{key}'")

    # ---- ShowLanguageDialog должен быть в [Setup], а не в [Code] ----
    code = "\n".join(l for _, l in sections.get("Code", []))
    for name in ("ShowLanguageDialog", "SelectLanguage"):
        if re.search(rf"\b{name}\s*\(", code):
            err(
                f"[Code]: '{name}(' вызвана как функция, а это директива [Setup] "
                f"(или встроенная только для {name}) — уберите вызов из [Code]"
            )

    # ---- {cm:...} ----
    defined = set()
    for n, line in sections.get("CustomMessages", []):
        m = re.match(r"^(?:(\w+)\.)?(\w+)\s*=", line.strip())
        if m:
            defined.add(m.group(2))
    used = set(re.findall(r"\{cm:(\w+)\}", raw)) | set(
        re.findall(r"CustomMessage\('(\w+)'\)", code)
    )
    for key in sorted(used - defined - STANDARD_CM):
        err(f"{{cm:{key}}} использован, но не объявлен в [CustomMessages]")
    for key in sorted(defined - used):
        warn(f"CustomMessage '{key}' объявлен, но нигде не использован")

    # ---- [Files]: файлы должны существовать ----
    for n, line in sections.get("Files", []):
        m = re.search(r'Source:\s*"([^"]+)"', line)
        if not m:
            err(f"[Files] строка {n}: нет Source:")
            continue
        src = m.group(1)
        if src.startswith("{") or "{" in src:
            continue
        if not _exists(src):
            err(f"[Files] строка {n}: нет файла {src} (искали {_iss_path(src)})")
        if "Tasks:" not in line and "portable.txt" in src:
            warn(f"[Files] строка {n}: portable.txt ставится всегда, а не по задаче")
        for flag in re.findall(r"Flags:\s*([^;]+)", line):
            for f in flag.split():
                if f not in KNOWN_FILES_FLAGS:
                    warn(f"[Files] строка {n}: незнакомый флаг '{f}'")

    # ---- [Icons]: exe/uninstallexe ----
    for n, line in sections.get("Icons", []):
        m = re.search(r'Filename:\s*"([^"]+)"', line)
        if not m:
            err(f"[Icons] строка {n}: нет Filename:")
            continue
        fn = m.group(1)
        if fn.startswith("{"):
            continue
        if not _exists(fn):
            err(f"[Icons] строка {n}: нет файла {fn}")

    # ---- [Setup] SetupIconFile / WizardImageFile ----
    for n, line in sections.get("Setup", []):
        for key in ("SetupIconFile", "WizardImageFile", "WizardSmallImageFile", "LicenseFile"):
            m = re.match(rf"{key}\s*=\s*(.+)$", line.strip())
            if m:
                src = m.group(1).strip().strip('"')
                if not src.startswith("{") and not _exists(src):
                    err(f"[Setup] строка {n}: {key} — нет файла {src}")

    # ---- [Code]: баланс begin/end, точки с запятой ----
    depth = 0
    for n, line in sections.get("Code", []):
        stripped = re.sub(r"\{[^}]*\}", "", line).strip()
        if not stripped or stripped.startswith(";"):
            continue
        # строковые литералы не должны содержать begin/end
        nolit = re.sub(r"'[^']*'", "''", stripped)
        # в Pascal свой end требует и begin, и try (try..finally/except..end)
        depth += len(re.findall(r"\b(?:begin|try)\b", nolit))
        depth -= len(re.findall(r"\bend\b", nolit))
        if depth < 0:
            err(f"[Code] строка {n}: лишний 'end'")
            depth = 0
    if depth != 0:
        err(f"[Code]: непарные begin/end, дисбаланс {depth}")

    # ---- CreateInputOptionPage: 7 аргументов ----
    m = re.search(r"CreateInputOptionPage\s*\((.*?)\);", code, re.S)
    if m:
        args = _split_args(m.group(1))
        if len(args) != 7:
            err(
                f"[Code]: CreateInputOptionPage вызван с {len(args)} аргументами, "
                f"а нужно 7 (AfterID, Caption, Description, SubCaption, "
                f"Options, AExclusive, AListBox)"
            )
    m = re.search(r"CreateInputQueryPage\s*\((.*?)\);", code, re.S)
    if m:
        args = _split_args(m.group(1))
        if len(args) != 6:
            err(f"[Code]: CreateInputQueryPage вызван с {len(args)} аргументами, а нужно 6")

    # ---- секции, которые Inno понимает ----
    known_sections = {
        "Setup", "Types", "Components", "Tasks", "Dirs", "Files", "Icons",
        "INI", "InstallDelete", "Languages", "Messages", "CustomMessages",
        "LangOptions", "Registry", "Run", "UninstallDelete", "UninstallRun",
        "Code", "ThirdParty", "Permissions",
    }
    for sec in sections:
        if sec not in known_sections:
            warn(f"незнакомая секция [{sec}]")

    # ---- отчёт ----
    try:
        shown = str(ISS.relative_to(ROOT))
    except ValueError:
        shown = str(ISS)
    print(f"проверяю {shown}")
    print(f"  секции: {', '.join(sorted(sections))}")
    for w in warnings:
        print(f"  ?  {w}")
    for e in errors:
        print(f"  X  {e}")
    if errors:
        print(f"\nОШИБОК: {len(errors)}")
        return 1
    print(f"\nвсё чисто ({len(warnings)} замечаний)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
