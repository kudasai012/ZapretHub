; Настройки установщика Zapret Hub.
;
; Две задачи этого файла.
;
; 1. Умное обновление. Человек ставит новую версию поверх прежней, и
;    установщик должен найти прежнюю папку сам: иначе новая версия встанет
;    в C:\Program Files\Zapret Hub, хотя прежняя стоит в другом месте.
;
;    Компоненты при обновлении больше не пропадают: они лежат не в папке
;    программы, а в %APPDATA%\ZapretHub, куда установщик не лезет.
;    Прежние версии держали их рядом с exe — поэтому поиск прежней папки
;    смотрит и на components, и на сам exe.
;
; 2. Удаление с компонентами. Папку программы деинсталлятор удаляет целиком,
;    а компоненты и настройки живут в %APPDATA%\ZapretHub — их убираем
;    отдельно, иначе человек удалил программу, а winws.exe с его списками
;    остался лежать на диске. И то и другое добивается после того, как обходы
;    погашены: пока winws.exe держит файлы (или пока работает служба zapret),
;    удаление до конца не доходит.
;
; Пишем на базовых инструкциях NSIS — без LogicLib и прочих наборов макросов:
; этот файл попадает в сборку один раз, а ошибка в нём обнаружится только у
; человека, когда он уже запустил установщик. Простые IfFileExists и StrCmp
; тут надёжнее любой удобной обёртки.

!define ZAPRET_REG_KEY "Software\Zapret Hub"
!define ZAPRET_EXE "Zapret Hub.exe"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall"
; запись автозапуска Windows: её пишет сама программа, и при удалении её
; обязательно надо убрать, иначе Windows будет запускать удалённый exe
!define RUN_KEY "Software\Microsoft\Windows\CurrentVersion\Run"
!define RUN_VALUE "ZapretHub"
; служба zapret поднимает winws.exe вместе с Windows: пока она работает,
; файлы компонентов заняты и не удаляются
!define ZAPRET_SERVICE "zapret"

/**
 * Примета нашей папки: рядом лежат компоненты или сама программа.
 * Вход и выход — $0 ("1" — наша папка, "0" — нет).
 * uniq — разные метки на каждый встав макроса.
 */
!macro isZapretFolder uniq
  IfFileExists "$0\components\zapret-discord-youtube\*.*" ours_${uniq}
  IfFileExists "$0\${ZAPRET_EXE}" ours_${uniq}
  IfFileExists "$0\ZapretHub.exe" ours_${uniq}
  StrCpy $0 "0"
  Goto oursDone_${uniq}
ours_${uniq}:
  StrCpy $0 "1"
oursDone_${uniq}:
!macroend

/** Ищет папку прежней установки и, если нашлась, ставит в неё. */
!macro findPreviousInstall
  Push $0   ; кандидат на проверку
  Push $1   ; найденная папка
  Push $2   ; номер подключа реестра
  Push $3   ; имя подключа реестра
  StrCpy $1 ""

  ; --- 1. Своя прежняя запись, затем запись electron-builder ----------
  ReadRegStr $0 HKLM "${ZAPRET_REG_KEY}" "InstallDir"
  StrCmp $0 "" 0 haveOwnFolder
  ReadRegStr $0 HKLM "Software\${APP_GUID}" "InstallLocation"
haveOwnFolder:
  StrCmp $0 "" noOwnFolder
  StrCpy $1 $0
noOwnFolder:

  ; --- 2. Прежняя версия ставилась иначе: Inno Setup ------------------
  ; Inno кладёт подключ в «…\Uninstall» с именем программы. Имя подключа
  ; зависело от прежней сборки, поэтому ищем не по имени, а по тому, что
  ; лежит в самой папке. Смотрим обе половины реестра: прежняя сборка могла
  ; быть 32-битной и записаться в Wow6432Node.
  StrCmp $1 "" 0 folderFound
  SetRegView 64
  Call findPreviousInUninstallKeys
  StrCmp $1 "" 0 restoreView
  SetRegView 32
  Call findPreviousInUninstallKeys
restoreView:
  ; программа 64-битная, поэтому замена половины реестра — наша временная
  ; уловка, а не новое правило для всего сценария
  SetRegView 64
folderFound:

  ; --- 3. Прежняя версия могла записать просто путь программы ----------
  StrCmp $1 "" 0 haveFolder
  ReadRegStr $0 HKLM "Software\Zapret Hub\Inno Setup: App Path" "ZapretHub"
  StrCmp $0 "" noInnoPath
  StrCpy $1 $0
noInnoPath:
haveFolder:

  ; --- Что нашли, то и ставим -----------------------------------------
  StrCmp $1 "" installDone
  StrCpy $0 $1
  !insertmacro isZapretFolder final
  StrCmp $0 "1" 0 installDone
  StrCpy $INSTDIR $1
installDone:

  Pop $3
  Pop $2
  Pop $1
  Pop $0
!macroend

/**
 * Проходит подключи удаления и, найдя наш, кладёт путь в $1.
 * EnumRegKey принимает четыре параметра: куда писать, корень, подключ, номер.
 *
 * !ifndef BUILD_UNINSTALLER — не случайность. Этот файл electron-builder
 * подключает и к установщику, и к деинсталлятору, но макрос customInit зовётся
 * только в установщике. Без этой скобки функция осталась бы в деинсталляторе
 * без единого вызова, и NSIS ругнулся бы на неё предупреждением 6010 — а
 * electron-builder считает предупреждения ошибками («-WX»), то есть сборка
 * падала бы уже без нашей помощи.
 */
!ifndef BUILD_UNINSTALLER
Function findPreviousInUninstallKeys
  StrCpy $2 0
previousScan:
  ClearErrors
  EnumRegKey $3 HKLM "${UNINSTALL_KEY}" $2
  IfErrors previousDone
  ReadRegStr $0 HKLM "${UNINSTALL_KEY}\$3" "InstallLocation"
  StrCmp $0 "" previousNext
  !insertmacro isZapretFolder scan
  StrCmp $0 "1" previousFound
previousNext:
  IntOp $2 $2 + 1
  IntCmp $2 96 previousDone previousScan previousScan
previousFound:
  ; проверка затёрла $0, поэтому путь перечитываем: иначе в $1 уехала бы
  ; цифра «1» и установщик встал бы в папку с именем «1»
  ReadRegStr $1 HKLM "${UNINSTALL_KEY}\$3" "InstallLocation"
previousDone:
  Return
FunctionEnd
!endif

; =============================================================== установка

!macro customInit
  ; Папку подставляем до страницы выбора папки: человек увидит её готовой и
  ; сможет изменить, но по умолчанию обновление встаёт на место.
  !insertmacro findPreviousInstall
!macroend

!macro customInstall
  ; Запоминаем свою папку для следующих обновлений — по своему ключу и по
  ; ключу Inno, чтобы нас находили и другие сборки.
  WriteRegStr HKLM "${ZAPRET_REG_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${ZAPRET_REG_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Zapret Hub\Inno Setup: App Path" "ZapretHub" "$INSTDIR"
!macroend

; ================================================================ удаление

/**
 * Гасит обходы до начала удаления.
 *
 * Пока winws.exe работает, его файлы заняты, и «RMDir /r» их пропускает —
 * папка компонентов остаётся на диске у человека, который программу удалил.
 * Служба zapret гасится и удаляется: она поднимает winws вместе с Windows,
 * то есть смогла бы воскресить обход уже из удалённой папки.
 */
!macro stopBypasses
  nsExec::ExecToLog 'sc stop ${ZAPRET_SERVICE}'
  ; sc останавливает службу не мгновенно — даём ей время отпустить файлы
  Sleep 2000
  nsExec::ExecToLog 'sc delete ${ZAPRET_SERVICE}'
  nsExec::ExecToLog 'taskkill /F /IM winws.exe /T'
  nsExec::ExecToLog 'taskkill /F /IM "TgWsProxy_windows.exe" /T'
  nsExec::ExecToLog 'taskkill /F /IM "${ZAPRET_EXE}" /T'
  Sleep 1000
!macroend

/** Самый ранний шаг удаления: обходы должны быть погашены до удаления файлов. */
!macro customUnInit
  !insertmacro stopBypasses
!macroend

!macro customUnInstall
  ; Деинсталлятор удаляет папку программы целиком, но если что-то держало
  ; файлы, часть остаётся. Повторяем: процессы уже погашены, но файлы могли
  ; освободиться не сразу. Это и есть «удалились и компоненты тоже».
  !insertmacro stopBypasses
  ; Компоненты и настройки: отдельная папка вне папки программы. Удаление
  ; программы удаляет и их — это и есть правило «удалил программу, удалились
  ; компоненты».
  ;
  ; Какую папку убирать, знает сама программа: electron/main/paths.ts берёт
  ; app.getPath('appData'), а это %APPDATA% (Roaming), и держит там ZapretHub.
  ; Прежняя сборка деинсталлятора чистила %LOCALAPPDATA%\ZapretHub — папку, в
  ; которой программа ничего не держит. Человек удалял программу, а скачанный
  ; пакет zapret со всеми списками оставался лежать на диске. Чистим обе: ту,
  ; где данные лежат сейчас, и ту, куда могла положить прежняя сборка.
  RMDir /r "$APPDATA\ZapretHub"
  RMDir /r "$LOCALAPPDATA\ZapretHub"
  ; Прежние версии держали всё в папке программы: убираем и оттуда.
  RMDir /r "$INSTDIR\components"
  RMDir /r "$INSTDIR\data"
  RMDir "$INSTDIR"

  ; Свои записи убираем сами.
  DeleteRegKey HKLM "${ZAPRET_REG_KEY}"

  ; Запись автозапуска. Без этого Windows продолжала бы запускать удалённый
  ; exe при каждом входе в систему. Лежит она не в нашем разделе, а в Run,
  ; поэтому убираем отдельно и в обеих половинах реестра: прежняя сборка могла
  ; записаться и туда, и туда.
  SetRegView 64
  DeleteRegValue HKCU "${RUN_KEY}" "${RUN_VALUE}"
  SetRegView 32
  DeleteRegValue HKCU "${RUN_KEY}" "${RUN_VALUE}"
  SetRegView 64
!macroend
