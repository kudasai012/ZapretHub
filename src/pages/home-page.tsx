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
import type { AppConfig, ComponentSnapshot, HomeState, ZapretState } from '@shared/contract'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { StatusDot, statusTone } from '@/components/status-dot'
import { cn } from '@/lib/utils'
import { useT } from '@/hooks/use-hub'
import { toast } from '@/hooks/use-toast'
import type { PageKey } from '@/components/app-shell'

/**
 * Главный экран.
 *
 * Сверху — общий запуск: одна кнопка, которая поднимает или гасит всё сразу.
 * Ниже — отдельные обходы, каждый со своим состоянием. Ниже — быстрые действия.
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

  const anyRunning = home?.anyRunning ?? false

  const toggleAll = async () => {
    setBusyAll(true)
    try {
      await (anyRunning ? window.hub.process.stopAll() : window.hub.process.startAll())
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

  const active = (home?.zapret.status === 'running' ? 1 : 0) + (home?.tgws.status === 'running' ? 1 : 0)

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

      {/* Общий запуск: главное действие первого экрана. */}
      <Card>
        <CardContent className="flex items-center gap-4 p-5">
          <span
            className={cn(
              'flex h-11 w-11 shrink-0 items-center justify-center rounded-full',
              anyRunning ? 'bg-muted text-muted-foreground' : 'bg-muted text-foreground'
            )}
          >
            <Power className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-medium">{anyRunning ? t('action.stop_all') : t('action.start_all')}</p>
            <p className="text-sm text-muted-foreground">
              {t('dash.summary', { active, total: 2 })}
            </p>
          </div>
          <Badge variant={anyRunning ? 'success' : 'muted'}>
            {anyRunning ? t('status.some_running') : t('status.all_stopped')}
          </Badge>
          <Button size="sm" onClick={() => void toggleAll()} disabled={busyAll} className="shrink-0">
            {anyRunning ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {anyRunning ? t('action.stop') : t('action.start')}
          </Button>
        </CardContent>
      </Card>

      {/* Отдельные обходы */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold text-muted-foreground">{t('home.bypasses')}</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <BypassCard
            config={config}
            snapshot={home?.zapret ?? null}
            zapret={home?.zapretState ?? null}
            onToggle={(running) => void toggleOne('zapret', running)}
            onInstall={() => void install('zapret')}
            busy={busyAll || pending === 'zapret'}
            onNavigate={onNavigate}
          />
          <BypassCard
            config={config}
            snapshot={home?.tgws ?? null}
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
          <span className="text-sm">{running ? t('common.running') : t('common.stopped')}</span>
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
          {/* «Не установлен» — не надпись, а кнопка: нажатие скачивает
              компонент. Раньше человек видел проблему и должен был сам идти
              на страницу «Компоненты» и искать там кнопку. */}
          {!snapshot.installed ? (
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
          ) : null}
        </div>

        {isZapret && zapret ? (
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="muted">
              {t('home.badge_game')} · {t(`zapret.game_mode_${zapret.gameMode}`)}
            </Badge>
            <Badge variant="muted">
              {t('home.badge_ipset')} · {t(`home.badge_ipset_${zapret.ipsetState}`)}
            </Badge>
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="muted">
              {t('home.badge_port')} · {config.tgws.port}
            </Badge>
            <Badge variant="muted">
              {t('home.badge_dc')} · {config.tgws.dcIp.length}
            </Badge>
          </div>
        )}

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

          {snapshot.reason ? (
            <span className="min-w-0 flex-1 truncate text-right text-xs text-muted-foreground">
              {snapshot.reason}
            </span>
          ) : null}
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
