import { useEffect, useState } from 'react'
import type { AppUpdateInfo, ComponentKey } from '@shared/contract'
import { AppShell, type PageKey } from '@/components/app-shell'
import { Toaster } from '@/components/toast-viewport'
import { toast } from '@/hooks/use-toast'
import { ErrorDialog } from '@/components/error-dialog'
import { MissingComponentsDialog } from '@/components/missing-components'
import {
  UpdateProgressDialog,
  ReleaseNotesDialog
} from '@/components/update-dialogs'
import {
  useComponents,
  useConfig,
  useDiagnostics,
  useErrorNotices,
  useT,
  useUpdateProgress,
  useZapret
} from '@/hooks/use-hub'
import { HomePage } from '@/pages/home-page'
import { ComponentsPage } from '@/pages/components-page'
import { DiagnosticsPage } from '@/pages/diagnostics-page'
import { SettingsPage } from '@/pages/settings-page'

/**
 * Корень интерфейса.
 *
 * Держит выбранный раздел и раздаёт состояние страницам. Всё общение с
 * главным процессом идёт через window.hub — настоящего Node здесь нет.
 */
export default function App() {
  const { config, save } = useConfig()
  const { home, refresh } = useComponents()
  const { state: zapret } = useZapret()
  const { progress } = useUpdateProgress()
  // Прогон стратегий идёт в главном процессе, поэтому его состояние живёт
  // здесь: ушёл с раздела диагностики — вернулся, прогон на месте.
  const diagnostics = useDiagnostics()
  // Свёрнутое окно скачивания: прогноз остаётся в боковом меню, поэтому
  // «Свернуть» не отменяет и не скрывает ход дела — окно просто уходит.
  const [progressMinimized, setProgressMinimized] = useState(false)
  const { notice, close: closeNotice } = useErrorNotices()
  const [page, setPage] = useState<PageKey>('home')

  /**
   * Установка недостающих компонентов из предложения при запуске.
   *
   * Тот же путь, что и кнопки «Скачать»: обновление и установка — одно и то
   * же действие, потому что install = скачать последний релиз на место.
   */
  const installMissing = async (keys: ComponentKey[]): Promise<void> => {
    for (const key of keys) {
      try {
        const result = await window.hub.updates.apply(key)
        if (!result.ok) {
          toast({ title: 'Не удалось скачать', description: result.message, variant: 'destructive' })
        }
      } catch (error) {
        toast({
          title: 'Не удалось скачать',
          description: error instanceof Error ? error.message : String(error),
          variant: 'destructive'
        })
      }
    }
    void refresh()
  }

  // Обновление программы приходит событием: проверка при запуске рассылает его
  // сама, поэтому плашка появляется без участия человека и висит, пока
  // обновление не поставят.
  const [appUpdate, setAppUpdate] = useState<AppUpdateInfo | null>(null)
  const [releaseOpen, setReleaseOpen] = useState(false)
  // Предложение установить компоненты: показываем при каждом запуске, пока
  // человек сам не нажмёт «Позже» или не поставит их.
  const [offerInstall, setOfferInstall] = useState(true)

  useEffect(() => {
    const off = window.hub.on('app-update:available', (info) => setAppUpdate(info))
    return off
  }, [])

  // Все хуки зовём до раннего возврата: иначе React считает, что их число
  // между отрисовками изменилось, и падает с ошибкой правил хуков.
  const t = useT(config?.general.language ?? 'ru')

  // До первого ответа главного процесса интерфейс не рисуем: иначе на секунду
  // мелькнули бы пустые поля, и человек успел бы ткнуть в них.
  if (!config) {
    return (
      <div className="flex h-full items-center justify-center bg-background">
        <span className="h-6 w-6 animate-spin-slow rounded-full border-2 border-muted border-t-foreground" />
      </div>
    )
  }

  return (
    <AppShell
      config={config}
      home={home}
      page={page}
      onNavigate={setPage}
      onCollapse={(collapsed) => void save({ general: { sidebarCollapsed: collapsed } })}
      appUpdate={appUpdate}
      onShowRelease={() => setReleaseOpen(true)}
      progress={progressMinimized ? progress : null}
      onOpenProgress={() => setProgressMinimized(false)}
    >
      {page === 'home' ? <HomePage config={config} home={home} onNavigate={setPage} /> : null}
      {page === 'components' ? (
        <ComponentsPage config={config} zapret={zapret} onRefresh={() => void refresh()} />
      ) : null}
      {page === 'diagnostics' ? (
        <DiagnosticsPage
          config={config}
          zapret={
            zapret
              ? { installed: zapret.installed, strategies: zapret.strategies, strategy: zapret.strategy }
              : null
          }
          run={diagnostics}
        />
      ) : null}
      {page === 'settings' ? (
        <SettingsPage config={config} home={home} onShowRelease={() => setReleaseOpen(true)} />
      ) : null}

      {/* Предложение при запуске: компонентов нет — скачать их прямо сейчас. */}
      <MissingComponentsDialog
        home={home}
        lang={config?.general.language ?? 'ru'}
        busy={progress !== null}
        dismissed={!offerInstall}
        onInstall={(keys) => void installMissing(keys)}
        onLater={() => setOfferInstall(false)}
      />

      {/* Окно хода обновления: появляется, как только что-то начало качаться. */}
      <UpdateProgressDialog
        progress={progress}
        minimized={progressMinimized}
        onMinimize={() => setProgressMinimized(true)}
        onOpen={() => setProgressMinimized(false)}
        t={t}
      />

      {/* Ошибка, которую надо увидеть: запуск, проверка, обновление, папка. */}
      <ErrorDialog notice={notice} onClose={closeNotice} t={t} />

      {/* Что изменилось в новой версии программы. */}
      <ReleaseNotesDialog
        info={appUpdate}
        open={releaseOpen}
        onOpenChange={setReleaseOpen}
        t={t}
      />

      <Toaster />
    </AppShell>
  )
}
