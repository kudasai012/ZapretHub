import { useState } from 'react'
import {
  Download,
  FolderOpen,
  Gauge,
  Globe,
  Layers,
  Play,
  Power,
  ScrollText,
  Send,
  Settings2,
  Square,
  Zap
} from 'lucide-react'
import type { AppConfig, ComponentKey, ComponentSnapshot, HomeState, ZapretState } from '@shared/contract'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { StatusDot, statusTone } from '@/components/status-dot'
import { cn } from '@/lib/utils'
import { CIRCLE_CLASS, isTransitioning, stateText, verdictOf } from '@/lib/verdict'
import { useT } from '@/hooks/use-hub'
import { toast } from '@/hooks/use-toast'
import type { PageKey } from '@/components/app-shell'

/**
 * Главный экран.
 *
 * Сверху — одна крупная карта «Обход»: она говорит словами, что происходит
 * («работает», «останавливается», «не запустился, причина: …»), и несёт
 * единственную кнопку, которая этим управляет. Ниже — компоненты по отдельности
 * и быстрые действия.
 */
export function HomePage({
  config,
  home,
  onNavigate
}: {
  config: AppConfig
  home: HomeState | null
  onNavigate: (page: PageKey) => void
}) {
  const t = useT(config.general.language)
  const [pending, setPending] = useState<'zapret' | 'tgws' | null>(null)
  const [busyAll, setBusyAll] = useState(false)

  const zapret = home?.zapret ?? null
  const tgws = home?.tgws ?? null
  const active = (zapret?.status === 'running' ? 1 : 0) + (tgws?.status === 'running' ? 1 : 0)
  const verdict = verdictOf(t, [zapret, tgws])
  const busy = busyAll || pending !== null || isTransitioning([zapret, tgws])
  /* Что сделает щелчок по карте: словами это уже написано в самой карте,
     поэтому подпись остаётся только в подсказке. */
  const actionLabel =
    verdict.action === 'start'
      ? t('home.by_start')
      : verdict.action === 'stop'
        ? t('home.by_stop')
        : t('home.by_install')

  /** Одно действие на всю карту: включить, выключить или скачать компоненты. */
  const mainAction = () => {
    if (busy) return
    if (verdict.action === 'start') void startAll()
    else if (verdict.action === 'stop') void stopAll()
    else void installMissing()
  }

  const startAll = async () => {
    setBusyAll(true)
    try {
      await window.hub.process.startAll()
    } finally {
      setBusyAll(false)
    }
  }

  const stopAll = async () => {
    setBusyAll(true)
    try {
      await window.hub.process.stopAll()
    } finally {
      setBusyAll(false)
    }
  }

  /**
   * Скачать то, чего не хватает.
   *
   * Качаем только отсутствующие компоненты: «Обновить всё» на странице
   * компонентов — про обновление, а здесь человек просто хочет, чтобы обход
   * заработал, и не должен получать переустановку того, что уже работает.
   */
  const installMissing = async () => {
    setBusyAll(true)
    try {
      for (const key of ['zapret', 'tgws'] as ComponentKey[]) {
        const snapshot = key === 'zapret' ? zapret : tgws
        if (snapshot?.installed) continue
        const result = await window.hub.updates.apply(key)
        if (!result.ok) {
          toast({ title: t('home.install_failed'), description: result.message, variant: 'destructive' })
        }
      }
    } finally {
      setBusyAll(false)
    }
  }

  const toggleOne = async (key: 'zapret' | 'tgws', running: boolean) => {
    setPending(key)
    try {
      await (running ? window.hub.process.stop(key) : window.hub.process.start(key))
    } finally {
      setPending(null)
    }
  }

  /**
   * Скачать недостающий компонент прямо с главного экрана.
   *
   * «Не установлен» раньше было просто надписью: чтобы что-то сделать, надо
   * было самому догадаться открыть «Компоненты» и найти кнопку в шапке панели.
   * Теперь скачивание начинается там, где человек увидел проблему.
   */
  const install = async (key: 'zapret' | 'tgws') => {
    setPending(key)
    try {
      const result = await window.hub.updates.apply(key)
      if (!result.ok) {
        toast({ title: t('home.install_failed'), description: result.message, variant: 'destructive' })
        return
      }
      toast({ title: t('home.installed', { name: key === 'zapret' ? 'Zapret' : 'TG WS Proxy' }), variant: 'success' })
      onNavigate('components')
    } finally {
      setPending(null)
    }
  }

  /**
   * Открыть папку в проводнике.
   *
   * Раньше кнопка не говорила ничего: и когда папка открылась, и когда нет.
   * Теперь при отказе человек видит путь и причину — окно ошибки показывает
   * их подробно, а тост коротко напоминает, что именно не открылось.
   */
  const openFolder = async (target: 'components' | 'logs') => {
    const result = await window.hub.shell.openPath(target)
    if (result.ok) {
      toast({ title: t('common.opened_folder'), description: result.path, variant: 'success' })
    } else {
      toast({
        title: target === 'components' ? t('dash.open_components_failed') : t('dash.open_logs_failed'),
        description: result.path,
        variant: 'destructive'
      })
    }
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{t('dash.title')}</h1>
        <p className="text-sm text-muted-foreground">{t('dash.subtitle')}</p>
      </header>

      {/*
        Обход: вся карта — одна кнопка. Панель сама включает и выключает оба
        компонента: тянуться к маленькой кнопке в углу незачем, когда человек
        щёлкает по состоянию, которое он только что прочитал.
      */}
      <Card className="overflow-hidden">
        <div
          role="button"
          tabIndex={0}
          aria-pressed={verdict.action === 'stop'}
          aria-label={verdict.headline}
          onClick={mainAction}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              mainAction()
            }
          }}
          className={cn(
            'flex cursor-pointer flex-col gap-5 p-5 text-left transition-colors',
            'hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring',
            'sm:flex-row sm:items-center',
            busy && 'cursor-default'
          )}
        >
          <span
            className={cn(
              'flex h-16 w-16 shrink-0 items-center justify-center rounded-full',
              CIRCLE_CLASS[verdict.tone]
            )}
          >
            <Power className="h-7 w-7" />
          </span>

          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex items-center gap-2">
              <StatusDot tone={verdict.tone} />
              <p className="truncate text-lg font-semibold tracking-tight">{verdict.headline}</p>
            </div>
            {/* Когда всё в порядке, вместо подробностей — чем именно управляет
                эта карта: непонятно было, что «обход» это и есть Discord,
                YouTube и Telegram вместе. */}
            <p className="text-sm text-muted-foreground">{verdict.detail || t('home.by_subtitle')}</p>
            <p className="text-xs text-muted-foreground">{t('dash.summary', { active, total: 2 })}</p>
          </div>

          {/* Кнопка без подписи: надпись «Включить обход» повторяла ровно то,
              что человек только что прочитал в этой же карте, — а вся карта и
              так нажимается целиком. Осталась одна иконка с подсказкой. */}
          <span
            aria-hidden="true"
            title={actionLabel}
            className={cn(
              buttonVariants({
                variant: verdict.action === 'stop' ? 'outline' : 'default',
                size: 'icon'
              }),
              'pointer-events-none h-11 w-11 shrink-0 rounded-full',
              busy && 'opacity-60'
            )}
          >
            {verdict.action === 'start' ? <Play className="h-5 w-5" /> : null}
            {verdict.action === 'stop' ? <Square className="h-5 w-5" /> : null}
            {verdict.action === 'install' ? <Download className="h-5 w-5" /> : null}
          </span>
        </div>
      </Card>

      {/* Компоненты */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold text-muted-foreground">{t('home.bypasses')}</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <BypassCard
            config={config}
            snapshot={zapret}
            zapret={home?.zapretState ?? null}
            onToggle={(running) => void toggleOne('zapret', running)}
            onInstall={() => void install('zapret')}
            busy={busyAll || pending === 'zapret'}
            onNavigate={onNavigate}
          />
          <BypassCard
            config={config}
            snapshot={tgws}
            zapret={null}
            onToggle={(running) => void toggleOne('tgws', running)}
            onInstall={() => void install('tgws')}
            busy={busyAll || pending === 'tgws'}
            onNavigate={onNavigate}
          />
        </div>
      </section>

      {/* Быстрые действия */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold text-muted-foreground">{t('dash.quick_actions')}</h2>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => onNavigate('components')}>
            <Layers className="h-3.5 w-3.5" />
            {t('components.open_settings')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void openFolder('components')}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            {t('dash.open_components')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void openFolder('logs')}
          >
            <ScrollText className="h-3.5 w-3.5" />
            {t('dash.open_logs')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onNavigate('diagnostics')}>
            <Gauge className="h-3.5 w-3.5" />
            {t('diag.title')}
          </Button>
        </div>
      </section>
    </div>
  )
}

function BypassCard({
  config,
  snapshot,
  zapret,
  onToggle,
  onInstall,
  busy,
  onNavigate
}: {
  config: AppConfig
  snapshot: ComponentSnapshot | null
  zapret: ZapretState | null
  onToggle: (running: boolean) => void
  /** Компонента нет — скачать его прямо отсюда. */
  onInstall: () => void
  /** Этот компонент сейчас чем-то занят: запуск, остановка или скачивание. */
  busy: boolean
  onNavigate: (page: PageKey) => void
}) {
  const t = useT(config.general.language)
  if (!snapshot) return null
  const running = snapshot.status === 'running'
  const isZapret = snapshot.key === 'zapret'
  const version = snapshot.version && snapshot.version !== '—' ? snapshot.version : t('comp.version_unknown')

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3 space-y-0 pb-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border bg-muted/40">
          {isZapret ? <Zap className="h-4 w-4" /> : <Globe className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <CardTitle className="truncate text-sm">
            {isZapret ? t('home.bypass_zapret') : t('home.bypass_tgws')}
          </CardTitle>
          <p className="truncate text-xs text-muted-foreground">
            {isZapret ? t('home.bypass_zapret_sub') : t('home.bypass_tgws_sub')}
          </p>
        </div>
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={() => onNavigate('components')}
          aria-label={t('components.open_settings')}
        >
          <Settings2 className="h-3.5 w-3.5" />
        </Button>
      </CardHeader>

      <CardContent className="space-y-3">
        <div className="flex items-center gap-2">
          <StatusDot tone={statusTone(snapshot.status)} />
          {/* Состояние словами. У неустановленного компонента вместо слов —
              кнопка «Не установлен»: нажатие скачивает его, и человеку не
              нужно идти за этим на страницу компонентов. */}
          {snapshot.installed ? (
            <span className="truncate text-sm">{stateText(t, snapshot)}</span>
          ) : (
            <button
              type="button"
              onClick={onInstall}
              disabled={busy}
              title={t('home.install_hint')}
              className="inline-flex items-center gap-1.5 rounded-full border border-warning/40 bg-warning/10 px-2.5 py-0.5 text-xs font-medium text-warning transition-colors hover:bg-warning/20 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-3 w-3" />
              {t('common.not_installed')}
            </button>
          )}
          {/* Разделитель между статусом и стратегией. Без него «Работает» и имя
              файла слипались в одну строку — читалось как одна фраза, и было
              непонятно, где кончается статус, а где начинается стратегия. */}
          {isZapret && zapret?.strategy ? (
            <span aria-hidden="true" className="shrink-0 text-muted-foreground/50">
              |
            </span>
          ) : null}
          {/* Какая стратегия работает — сразу у статуса: раньше, чтобы это
              узнать, приходилось идти в «Компоненты» и всматриваться в
              выпадающий список. Имя файла, как в пакете zapret. */}
          {isZapret && zapret?.strategy ? (
            <span
              className="truncate font-mono text-[11px] text-muted-foreground"
              title={`${t('home.badge_strategy')}: ${zapret.strategy}`}
            >
              {zapret.strategy}
            </span>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {/* Версия компонента: раньше её было видно только на странице
              компонентов, и непонятно было, что именно стоит и работает. */}
          <Badge variant="muted">
            {t('comp.version')} · {version}
          </Badge>
          {isZapret && zapret ? (
            <>
              <Badge variant="muted">
                {t('home.badge_game')} · {t(`zapret.game_mode_${zapret.gameMode}`)}
              </Badge>
              <Badge variant="muted">
                {t('home.badge_ipset')} · {t(`home.badge_ipset_${zapret.ipsetState}`)}
              </Badge>
            </>
          ) : (
            <>
              <Badge variant="muted">
                {t('home.badge_port')} · {config.tgws.port}
              </Badge>
              <Badge variant="muted">
                {t('home.badge_dc')} · {config.tgws.dcIp.length}
              </Badge>
            </>
          )}
        </div>

        <Separator />

        <div className="flex items-center justify-between gap-2">
          {snapshot.installed ? (
            <Button variant={running ? 'outline' : 'default'} size="sm" onClick={() => onToggle(running)} disabled={busy}>
              {running ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              {running ? t('action.stop') : t('action.start')}
            </Button>
          ) : (
            <Button size="sm" onClick={onInstall} disabled={busy}>
              <Download className="h-3.5 w-3.5" />
              {t('home.install')}
            </Button>
          )}

          {/* Только у телеграма: ссылка открывает прокси в самом Telegram,
              а не в браузере. */}
          {isZapret ? null : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void window.hub.shell.openUrl(proxyLink(config.tgws))}
              title={t('home.open_in_telegram')}
            >
              <Send className="h-3.5 w-3.5" />
              {t('home.open_in_telegram')}
            </Button>
          )}

          {/* Причина в статусе уже показана — здесь она не повторяется. */}
        </div>
      </CardContent>
    </Card>
  )
}

/**
 * Ссылка на прокси для Telegram.
 *
 * tg:// открывает само приложение, если оно установлено, и сразу показывает
 * экран подтверждения прокси — вместо браузера.
 */
function proxyLink(settings: AppConfig['tgws']): string {
  const query = `server=${encodeURIComponent(settings.host)}&port=${settings.port}&secret=${encodeURIComponent(settings.secret)}`
  return `tg://proxy?${query}`
}
