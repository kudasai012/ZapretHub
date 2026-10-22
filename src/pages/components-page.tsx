import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  Check,
  ChevronDown,
  Copy,
  Download,
  ExternalLink,
  FolderOpen,
  Gamepad2,
  Globe,
  ListTree,
  Radio,
  RotateCcw,
  Route,
  Server,
  Trash2,
  Zap
} from 'lucide-react'
import type {
  AppConfig,
  ComponentKey,
  TgwsState,
  UpdateInfo,
  ZapretState
} from '@shared/contract'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { StatusDot, statusTone } from '@/components/status-dot'
import { cn } from '@/lib/utils'
import { listNote, listTitle } from '@/lib/list-names'
import { useAction, useT } from '@/hooks/use-hub'
import { useRemembered } from '@/lib/utils'
import { toast } from '@/hooks/use-toast'

/**
 * Страница компонентов: настройки каждого обхода отдельно.
 *
 * Панели свёртываются нажатием на название — как в прежней версии: когда
 * оба обхода настроены, незачем видеть оба набора полей сразу.
 */
export function ComponentsPage({
  config,
  zapret,
  onRefresh
}: {
  config: AppConfig
  zapret: ZapretState | null
  onRefresh: () => void
}) {
  const t = useT(config.general.language)
  const action = useAction(t)
  const [tgws, setTgws] = useState<TgwsState | null>(null)
  const [available, setAvailable] = useState<UpdateInfo[]>([])
  // свёрнутость панелей запоминается: сменил раздел — вернулся, всё как оставил
  const [openZapret, setOpenZapret] = useRemembered('zapret.panel.zapret', true)
  const [openTgws, setOpenTgws] = useRemembered('zapret.panel.tgws', true)
  const [busyAll, setBusyAll] = useState(false)

  const refresh = useCallback(async () => {
    setTgws(await window.hub.tgws.snapshot())
  }, [])

  // Кнопки «Перечитать сведения» здесь больше нет: состояние и так приходит
  // событиями от главного процесса, и кнопка ничего не меняла на экране.
  // Состояние переспрашивается само после установки и обновления.

  useEffect(() => {
    void refresh()
    const off = window.hub.on('tgws:state', setTgws)
    // версии спрашиваем молча: «Доступно 1.10.4» под названием компонента
    void window.hub.updates.check(false).then((result) => setAvailable(result.checked)).catch(() => {})
    return off
  }, [refresh])

  /**
   * После установки или обновления версии спрашиваем заново.
   *
   * Иначе плашка «Доступно 1.10.4» остаётся висеть над компонентом, который
   * только что обновили, — и человек не понимает, обновилось или нет.
   */
  const versionsChanged = useCallback(() => {
    void window.hub.updates.check(true).then((result) => setAvailable(result.checked)).catch(() => {})
  }, [])

  const installed = { zapret: zapret?.installed ?? false, tgws: tgws?.installed ?? false }
  const anyMissing = !installed.zapret || !installed.tgws
  const anyUpdate = available.length > 0

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{t('components.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('components.subtitle')}</p>
        </div>

        {/* Общая кнопка: ставит всё, если чего-то не хватает, иначе обновляет всё.
            Если обновляться нечему — говорит об этом, а не качает заново. */}
        <Button
          size="sm"
          disabled={busyAll}
          onClick={() => {
            if (!anyMissing && !anyUpdate) {
              // Всё уже свежее свежего: раньше кнопка молча качала компоненты
              // заново, и человек не понимал, зачем она ему понадобилась.
              toast({ title: t('upd.actual_all'), variant: 'success' })
              return
            }
            void action(
              (async () => {
                setBusyAll(true)
                try {
                  const lines: string[] = []
                  for (const key of ['zapret', 'tgws'] as ComponentKey[]) {
                    const result = await window.hub.updates.apply(key)
                    lines.push(result.message)
                  }
                  onRefresh()
                  await refresh()
                  await versionsChanged()
                  return lines.join('\n')
                } finally {
                  setBusyAll(false)
                }
              })(),
              {
                success: t(anyMissing ? 'upd.install_all' : 'upd.update_all'),
                failure: t('upd.update_failed')
              }
            )
          }}
        >
          <Download className="h-3.5 w-3.5" />
          {anyMissing ? t('upd.install_all') : t('upd.update_all')}
          {anyUpdate && !anyMissing ? ` · ${available.length}` : ''}
        </Button>
      </header>

      <ZapretPanel
        config={config}
        zapret={zapret}
        info={available.find((item) => item.key === 'zapret') ?? null}
        open={openZapret}
        onToggleOpen={() => setOpenZapret(!openZapret)}
        onRefresh={onRefresh}
        onUpdated={versionsChanged}
        t={t}
      />

      <TgwsPanel
        tgws={tgws}
        info={available.find((item) => item.key === 'tgws') ?? null}
        open={openTgws}
        onToggleOpen={() => setOpenTgws(!openTgws)}
        onRefresh={onRefresh}
        onUpdated={versionsChanged}
        t={t}
      />
    </div>
  )
}

/**
 * Шапка панели: нажатие на название сворачивает и разворачивает её.
 *
 * Кнопка установки стоит рядом со статусом версии: статус и действие по нему
 * должны быть в одном месте, иначе приходится искать кнопку внизу панели, а
 * версию читать сверху.
 */
function PanelHeader({
  icon,
  title,
  subtitle,
  installed,
  info,
  open,
  onToggle,
  onApply,
  t
}: {
  icon: React.ReactNode
  title: string
  subtitle: string
  installed: boolean
  info: UpdateInfo | null
  open: boolean
  onToggle: () => void
  onApply: () => void
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  return (
    <CardHeader className="p-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        title={t('comp.panel_hint')}
        className="flex w-full items-center gap-3 p-5 text-left transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border bg-muted/40">
          {icon}
        </span>

        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{title}</span>
          <span className="block truncate text-xs text-muted-foreground">{subtitle}</span>
        </span>

        {/* Кнопка вне области сворачивания: щелчок по ней не должен
            складывать панель. Стоит слева от статуса версии — сначала
            действие, потом его результат. */}
        <span
          className="shrink-0"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
          role="presentation"
        >
          <Button
            size="sm"
            variant="outline"
            className="h-7 gap-1.5 text-xs"
            onClick={onApply}
            title={t(installed ? 'upd.update_one' : 'upd.install_one')}
          >
            <Download className="h-3 w-3" />
            {installed ? t('upd.update_one') : t('upd.install_one')}
          </Button>
        </span>

        {/* Мини-окно версии: что стоит и что вышло. */}
        <span className="flex shrink-0 items-center gap-1.5">
          {!installed ? (
            <Badge variant="warning">{t('common.not_installed')}</Badge>
          ) : info ? (
            <>
              <Badge variant="muted">
                {t('comp.installed_version')} {info.current}
              </Badge>
              <Badge variant="success">
                {t('comp.available_version')} {info.latest}
              </Badge>
            </>
          ) : (
            <Badge variant="muted">{t('upd.up_to_date')}</Badge>
          )}
        </span>

        <ChevronDown
          className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', !open && '-rotate-90')}
        />
      </button>
    </CardHeader>
  )
}

/**
 * Папка пакета на диске.
 *
 * Показываем её только когда имя необычное: программа умеет находить пакет
 * там, где его положили (прежняя версия, распакованный архив, ручная
 * раскладка), и человеку важно видеть, откуда взялись файлы — иначе
 * непонятно, откуда вдруг работает обход, которого «не установлен».
 */
function FolderNote({
  dir,
  standard,
  t
}: {
  dir: string
  standard: RegExp
  t: (key: string) => string
}) {
  if (!dir || standard.test(dir)) return null
  return (
    <p className="text-[11px] text-muted-foreground" title={dir}>
      {t('comp.folder_found')}: <span className="font-mono">{dir}</span>
    </p>
  )
}

/**
 * Раздел панели: заголовок с иконкой, подпись и содержимое.
 *
 * Раньше все разделы панели выглядели одинаково — просто подпись и поле под
 * ней, — и глазами приходилось искать, где Game Filter, а где списки. Теперь у
 * каждого раздела свой значок и своя подложка: разделы читаются по иконкам, а
 * не по расстоянию между ними.
 */
function Section({
  icon,
  title,
  hint,
  children,
  tone = 'plain'
}: {
  icon: React.ReactNode
  title: string
  hint?: string
  children: React.ReactNode
  /** plain — обычный раздел, soft — с подложкой, чтобы чередоваться. */
  tone?: 'plain' | 'soft'
}) {
  return (
    <section
      className={cn(
        'space-y-3 rounded-md p-3.5',
        tone === 'soft' ? 'border bg-muted/20' : 'border border-transparent'
      )}
    >
      <header className="flex items-center gap-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border bg-background text-muted-foreground">
          {icon}
        </span>
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold leading-tight">{title}</h3>
          {hint ? <p className="text-[11px] leading-tight text-muted-foreground">{hint}</p> : null}
        </div>
      </header>
      {children}
    </section>
  )
}

/** Иконки разделов: по одному значку на смысл, чтобы раздел узнавался. */
const SECTION_ICONS = {
  status: <Activity className="h-3.5 w-3.5" />,
  strategy: <Route className="h-3.5 w-3.5" />,
  game: <Gamepad2 className="h-3.5 w-3.5" />,
  ipset: <Globe className="h-3.5 w-3.5" />,
  lists: <ListTree className="h-3.5 w-3.5" />,
  service: <Server className="h-3.5 w-3.5" />,
  proxy: <Radio className="h-3.5 w-3.5" />
}

// ------------------------------------------------------------------ zapret

function ZapretPanel({
  config,
  zapret,
  info,
  open,
  onToggleOpen,
  onRefresh,
  onUpdated,
  t
}: {
  config: AppConfig
  zapret: ZapretState | null
  info: UpdateInfo | null
  open: boolean
  onToggleOpen: () => void
  onRefresh: () => void
  /** Компонент обновился: версии на экране пора переспросить. */
  onUpdated: () => void
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  const action = useAction(t)
  const [listName, setListName] = useState<string | null>(null)
  const [listText, setListText] = useState('')
  const [busy, setBusy] = useState(false)
  /** Ставит или обновляет компонент; кнопка стоит в шапке панели. */
  const applyUpdate = () => {
    void action(window.hub.updates.apply('zapret'), {
      success: t('upd.download'),
      failure: t('upd.update_failed')
    }).then((result) => {
      if (!result) return
      onRefresh()
      onUpdated()
    })
  }

  if (!zapret) return null

  const openList = async (name: string) => {
    setListName(name)
    setListText(await window.hub.zapret.readList(name))
  }

  /**
   * Стратегия, списки, игровой фильтр и режим IPSet — всё это части командной
   * строки winws, которую он разобрал при запуске. Без перезапуска такая правка
   * просто лежит в файле настроек, а обход продолжает работать по-старому:
   * человек меняет настройку, получает «применено» и не видит разницы. Поэтому
   * каждая такая правка перезапускает обход — или честно говорит, что применится
   * при следующем запуске, если обход сейчас выключен.
   */
  const restartIfRunning = async (): Promise<{ ok: boolean; reason: string }> => {
    if (zapret.status !== 'running') return { ok: true, reason: '' }
    const stopped = await window.hub.process.stop('zapret')
    if (!stopped.ok) return stopped
    const started = await window.hub.process.start('zapret')
    if (started.ok) onRefresh()
    return started
  }

  /** Правка настройки + перезапуск обхода + честный ответ на экране. */
  const applyCommandLine = async (
    save: () => Promise<unknown>,
    wasRunning: boolean,
    restarted: string,
    stopped: string
  ) => {
    setBusy(true)
    try {
      await save()
      onRefresh()
      const result = await restartIfRunning()
      if (!result.ok) {
        toast({ title: t('zapret.restart_failed', { error: result.reason }), variant: 'destructive' })
        return
      }
      toast({ title: wasRunning ? restarted : stopped, variant: 'success' })
    } finally {
      setBusy(false)
    }
  }

  const applyStrategy = async (name: string) => {
    await applyCommandLine(
      () => window.hub.zapret.setStrategy(name),
      zapret.status === 'running',
      t('zapret.strategy_restarted', { name }),
      t('zapret.strategy_applied', { name })
    )
  }

  // Список меняет правила, которые winws применил при старте,
  // поэтому после записи обход нужно перезапустить — иначе файл сохранён, но не действует.
  const saveList = async () => {
    if (!listName) return
    await applyCommandLine(
      () => window.hub.zapret.writeList(listName, listText),
      zapret.status === 'running',
      t('zapret.list_saved_restarted', { name: listTitle(listName, config.general.language) }),
      t('zapret.list_saved_stopped', { name: listTitle(listName, config.general.language) })
    )
  }

  return (
    <Card>
      <PanelHeader
        icon={<Zap className="h-4 w-4" />}
        title={t('zapret.title')}
        subtitle="Flowseal / zapret-discord-youtube"
        installed={zapret.installed}
        info={info}
        open={open}
        onToggle={onToggleOpen}
        onApply={applyUpdate}
        t={t}
      />

      {open ? (
        <CardContent className="space-y-3 border-t pt-4">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1">
            <StatusDot tone={statusTone(zapret.status)} />
            <span className="text-sm">{zapret.status === 'running' ? t('common.running') : t('common.stopped')}</span>
            <FolderNote dir={zapret.dir} standard={/(^|\\)components[\\/]zapret-discord-youtube$/i} t={t} />
          </div>

          {!zapret.installed ? (
            <p className="rounded-md border border-warning/30 bg-warning/5 p-3 text-xs text-muted-foreground">
              {t('components.install_hint')}
            </p>
          ) : null}

          {/* Стратегия: одна кнопка, по щелчку — список, выбираешь нужную.
              Меню рисуем сами и держим его под кнопкой (position: absolute у
              обёртки), а не отдаём в руки выпадающему компоненту: тот сам решал,
              куда ему встать, и при прокрутке раздела уводил список к верху
              экрана — нижние стратегии оказывались за краем и не нажимались. */}
          <Section icon={SECTION_ICONS.strategy} title={t('zapret.strategy')} hint={t('zapret.strategy_hint')}>
            {zapret.strategies.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t('zapret.no_strategies')}</p>
            ) : (
              <StrategyPicker
                strategies={zapret.strategies}
                value={zapret.strategy}
                onPick={(name) => {
                  if (name !== zapret.strategy) void applyStrategy(name)
                }}
                label={t('zapret.strategy')}
              />
            )}
          </Section>

          {/* Game Filter */}
          <Section icon={SECTION_ICONS.game} title={t('zapret.game_filter')} hint={t('zapret.game_filter_hint')} tone="soft">
            <Select
              value={zapret.gameMode}
              onValueChange={(value) => {
                void applyCommandLine(
                  () => window.hub.zapret.setGameFilter({ mode: value }),
                  zapret.status === 'running',
                  t('zapret.game_restarted', { mode: value }),
                  t('zapret.game_applied', { mode: value })
                )
              }}
            >
              <SelectTrigger id="game-mode" aria-label={t('zapret.game_filter')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="disabled">{t('zapret.game_mode_disabled')}</SelectItem>
                <SelectItem value="tcp">{t('zapret.game_mode_tcp')}</SelectItem>
                <SelectItem value="udp">{t('zapret.game_mode_udp')}</SelectItem>
                <SelectItem value="all">{t('zapret.game_mode_all')}</SelectItem>
              </SelectContent>
            </Select>

            {zapret.gameMode !== 'disabled' ? (
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="tcp-range" className="text-xs text-muted-foreground">
                    {t('zapret.game_tcp_range')}
                  </Label>
                  <Input
                    id="tcp-range"
                    value={zapret.gameTcpRange}
                    onChange={(event) =>
                      void action(window.hub.zapret.setGameFilter({ tcp: event.target.value }), {})
                    }
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="udp-range" className="text-xs text-muted-foreground">
                    {t('zapret.game_udp_range')}
                  </Label>
                  <Input
                    id="udp-range"
                    value={zapret.gameUdpRange}
                    onChange={(event) =>
                      void action(window.hub.zapret.setGameFilter({ udp: event.target.value }), {})
                    }
                  />
                </div>
              </div>
            ) : null}
          </Section>


          {/* IPSet */}
          <Section icon={SECTION_ICONS.ipset} title={t('zapret.ipset')} hint={t('zapret.ipset_hint')}>
            <Select
              value={zapret.ipsetMode}
              onValueChange={(value) => {
                void applyCommandLine(
                  () => window.hub.zapret.setIpsetMode(value),
                  zapret.status === 'running',
                  t('zapret.ipset_restarted', { mode: value }),
                  t('zapret.ipset_applied', { mode: value })
                )
              }}
            >
              <SelectTrigger id="ipset-mode" aria-label={t('zapret.ipset')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="loaded">{t('zapret.ipset_loaded')}</SelectItem>
                <SelectItem value="none">{t('zapret.ipset_none')}</SelectItem>
                <SelectItem value="any">{t('zapret.ipset_any')}</SelectItem>
              </SelectContent>
            </Select>
          </Section>

          {/* Списки адресов: сначала выбираем файл, потом правим его. */}
          <Section
            icon={SECTION_ICONS.lists}
            title={t('zapret.user_lists')}
            hint={t('zapret.user_lists_hint')}
            tone="soft"
          >
            <Select
              value={listName ?? ''}
              onValueChange={(value) => void openList(value)}
            >
              <SelectTrigger id="list-pick">
                <SelectValue placeholder={t('comp.choose_list')} />
              </SelectTrigger>
              <SelectContent>
                {zapret.lists.map((name) => (
                  <SelectItem key={name} value={name} title={listNote(name, config.general.language)}>
                    <span className="font-mono text-xs">{listTitle(name, config.general.language)}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {listName ? (
              <div className="space-y-2 pt-1">
                <textarea
                  value={listText}
                  onChange={(event) => setListText(event.target.value)}
                  spellCheck={false}
                  aria-label={listTitle(listName, config.general.language)}
                  title={`${listTitle(listName, config.general.language)} — ${listNote(listName, config.general.language)}`}
                  className="h-48 w-full resize-y rounded-md border border-input bg-transparent p-3 font-mono text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => void saveList()} disabled={busy}>
                    {t('common.save')}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setListName(null)}>
                    {t('common.cancel')}
                  </Button>
                </div>
              </div>
            ) : null}
          </Section>

          {/* Служба Windows мешает: winws.exe не стартует второй копией. */}
          {zapret.serviceState && zapret.serviceState !== 'STOPPED' ? (
            <>
              <Separator />
              <div className="space-y-2">
                <p className="text-xs text-warning">{t('zapret.service_conflict')}</p>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() =>
                    void action(window.hub.zapret.removeService(), {
                      success: t('zapret.service_removed')
                    })
                  }
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {t('zapret.service_remove')}
                </Button>
              </div>
            </>
          ) : null}

          <Separator />

          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void action(window.hub.shell.openPath('components'), {})}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              {t('common.open_folder')}
            </Button>
          </div>
        </CardContent>
      ) : null}
    </Card>
  )
}

// ------------------------------------------------------------------ tgws

function TgwsPanel({
  tgws,
  info,
  open,
  onToggleOpen,
  onRefresh,
  onUpdated,
  t
}: {
  tgws: TgwsState | null
  info: UpdateInfo | null
  open: boolean
  onToggleOpen: () => void
  onRefresh: () => void
  /** Компонент обновился: версии на экране пора переспросить. */
  onUpdated: () => void
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  const action = useAction(t)

  if (!tgws) return null
  const settings = tgws.settings

  /** Ставит или обновляет компонент; кнопка стоит в шапке панели. */
  const applyUpdate = () => {
    void action(window.hub.updates.apply('tgws'), {
      success: t('upd.download'),
      failure: t('upd.update_failed')
    }).then((result) => {
      if (!result) return
      onRefresh()
      onUpdated()
    })
  }

  const update = (patch: Record<string, unknown>) => {
    void action(window.hub.tgws.saveSettings(patch), { success: t('tgws.config_applied') })
  }

  const link = `https://t.me/proxy?server=${settings.host}&port=${settings.port}&secret=${settings.secret}`

  return (
    <Card>
      <PanelHeader
        icon={<ExternalLink className="h-4 w-4" />}
        title={t('tgws.title')}
        subtitle="Flowseal / tg-ws-proxy"
        installed={tgws.installed}
        info={info}
        open={open}
        onToggle={onToggleOpen}
        onApply={applyUpdate}
        t={t}
      />

      {open ? (
        <CardContent className="space-y-5 border-t pt-5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <StatusDot tone={statusTone(tgws.status)} />
            <span className="text-sm">{tgws.status === 'running' ? t('common.running') : t('common.stopped')}</span>
            <FolderNote dir={tgws.dir} standard={/(^|\\)components[\\/]tg-ws-proxy$/i} t={t} />
          </div>

          {!tgws.installed ? (
            <p className="rounded-md border border-warning/30 bg-warning/5 p-3 text-xs text-muted-foreground">
              {t('components.install_hint')}
            </p>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="tgws-host">{t('tgws.host')}</Label>
              <Input
                id="tgws-host"
                value={settings.host}
                onChange={(event) => update({ host: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tgws-port">{t('tgws.port')}</Label>
              <Input
                id="tgws-port"
                type="number"
                min={1}
                max={65535}
                value={settings.port}
                onChange={(event) => update({ port: Number(event.target.value) })}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tgws-secret">{t('tgws.secret')}</Label>
            <div className="flex gap-2">
              <Input
                id="tgws-secret"
                value={settings.secret}
                className="font-mono"
                onChange={(event) => update({ secret: event.target.value })}
              />
              <Button
                variant="outline"
                size="icon"
                onClick={() =>
                  update({
                    secret: Array.from(crypto.getRandomValues(new Uint8Array(16)))
                      .map((byte) => byte.toString(16).padStart(2, '0'))
                      .join('')
                  })
                }
                aria-label={t('tgws.generate')}
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tgws-dc">{t('tgws.dc_ip')}</Label>
            <textarea
              id="tgws-dc"
              value={settings.dcIp.join('\n')}
              onChange={(event) =>
                update({ dcIp: event.target.value.split('\n').map((line) => line.trim()).filter(Boolean) })
              }
              spellCheck={false}
              className="h-24 w-full resize-y rounded-md border border-input bg-transparent p-3 font-mono text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <Separator />

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="tgws-buf" className="text-xs text-muted-foreground">
                {t('tgws.buf_kb')}
              </Label>
              <Input
                id="tgws-buf"
                type="number"
                value={settings.bufKb}
                onChange={(event) => update({ bufKb: Number(event.target.value) })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tgws-pool" className="text-xs text-muted-foreground">
                {t('tgws.pool_size')}
              </Label>
              <Input
                id="tgws-pool"
                type="number"
                value={settings.poolSize}
                onChange={(event) => update({ poolSize: Number(event.target.value) })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tgws-log" className="text-xs text-muted-foreground">
                {t('log.title')} · MB
              </Label>
              <Input
                id="tgws-log"
                type="number"
                value={settings.logMaxMb}
                onChange={(event) => update({ logMaxMb: Number(event.target.value) })}
              />
            </div>
          </div>

          <div className="space-y-1">
            <ToggleRow
              label={t('tgws.verbose')}
              checked={settings.verbose}
              onChange={(value) => update({ verbose: value })}
            />
            <ToggleRow
              label={t('tgws.cfproxy')}
              checked={settings.cfproxy}
              onChange={(value) => update({ cfproxy: value })}
            />
            <ToggleRow
              label={t('tgws.force_test_dc')}
              checked={settings.forceTestDc}
              onChange={(value) => update({ forceTestDc: value })}
            />
            <ToggleRow
              label={t('tgws.no_secure')}
              checked={settings.noSecure}
              onChange={(value) => update({ noSecure: value })}
            />
          </div>

          <Separator />

          {/* Ссылка для Telegram: её можно просто скопировать и вставить в настройки. */}
          <div className="space-y-2">
            <Label>{t('tgws.link')}</Label>
            <div className="flex gap-2">
              <Input readOnly value={link} className="font-mono text-xs" />
              <Button
                variant="outline"
                size="icon"
                onClick={() => {
                  void navigator.clipboard.writeText(link)
                  toast({ title: t('tgws.link_copied'), variant: 'success' })
                }}
                aria-label={t('tgws.copy_link')}
              >
                <Copy className="h-3.5 w-3.5" />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">{t('tgws.manual_hint')}</p>
          </div>

          <Separator />

          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void action(window.hub.shell.openPath('components'), {})}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              {t('common.open_folder')}
            </Button>
          </div>
        </CardContent>
      ) : null}
    </Card>
  )
}

/** Строка «подпись — тумблер». */
function ToggleRow({
  label,
  checked,
  onChange
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 rounded-md px-1 py-1.5 hover:bg-accent/40">
      <span className="text-sm">{label}</span>
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  )
}

/**
 * Выбор стратегии: кнопка и список под ней.
 *
 * Почему не готовая выпадашка: она открывается там, где решит она, — при
 * прокрутке раздела список уезжал к верху экрана, нижние стратегии оказывались
 * за краем и не нажимались. Здесь список всегда под кнопкой, в своём окне с
 * прокруткой, и закрывается сам — выбором, щелчком мимо или Escape.
 */
function StrategyPicker({
  strategies,
  value,
  onPick,
  label
}: {
  strategies: string[]
  value: string
  onPick: (name: string) => void
  label: string
}) {
  const [open, setOpen] = useState(false)
  const [dropUp, setDropUp] = useState(false)
  const [cursor, setCursor] = useState(() => Math.max(0, strategies.indexOf(value)))
  const wrap = useRef<HTMLDivElement>(null)

  /**
   * Открыть список — вниз или вверх.
   *
   * Список всегда рисуем у кнопки, но если под кнопкой места меньше, чем нужно
   * списку, он уходил бы за нижний край окна: нижние стратегии оказались бы за
   * краем, и до них не докликнуться. Поэтому в таком случае список растёт
   * вверх. 288 — высота самого длинного списка (max-h-72), плюс запас.
   */
  const openList = () => {
    const box = wrap.current?.getBoundingClientRect()
    const below = window.innerHeight - (box?.bottom ?? 0)
    setDropUp(below < 320)
    setCursor(Math.max(0, strategies.indexOf(value)))
    setOpen(true)
  }

  // Щёлкнули мимо — закрываем. Слушаем нажатие, а не щелчок: иначе список
  // закрывался бы раньше, чем до кнопки внутри него долетала мышь.
  useEffect(() => {
    if (!open) return
    const away = (event: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open])

  // Стратегии могли пересчитаться (обновился пакет): курсор не должен уехать
  // за пределы списка.
  useEffect(() => {
    setCursor((current) => Math.min(current, strategies.length - 1))
  }, [strategies.length])

  const move = (step: number) => {
    setCursor((current) => {
      const next = Math.min(strategies.length - 1, Math.max(0, current + step))
      return next
    })
  }

  const choose = (index: number) => {
    setOpen(false)
    onPick(strategies[index])
  }

  return (
    <div ref={wrap} className="relative">
      <Button
        id="strategy"
        type="button"
        variant="outline"
        size="sm"
        aria-haspopup="listbox"
        aria-expanded={open}
        className="w-full justify-between font-mono text-xs"
        onClick={() => {
          if (open) setOpen(false)
          else openList()
        }}
        aria-activedescendant={open ? `strategy-option-${cursor}` : undefined}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            if (!open) openList()
            move(event.key === 'ArrowDown' ? 1 : -1)
          } else if (event.key === 'Enter' || event.key === ' ') {
            // Клавиатура: открыли список, дошли стрелками до нужной стратегии —
            // Enter выбирает её, а не закрывает список, как было бы по
            // обычному поведению кнопки.
            event.preventDefault()
            if (open) choose(cursor)
            else openList()
          } else if (event.key === 'Escape') {
            setOpen(false)
          }
        }}
      >
        <span className="truncate">{value || strategies[0]}</span>
        <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 opacity-60 transition-transform', open && 'rotate-180')} />
      </Button>

      {open ? (
        <div
          role="listbox"
          aria-label={label}
          className={cn(
            'absolute left-0 right-0 z-50 max-h-72 overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-md',
            dropUp ? 'bottom-full mb-1' : 'top-full mt-1'
          )}
        >
          {strategies.map((name, index) => {
            const current = name === value
            return (
              <button
                key={name}
                id={`strategy-option-${index}`}
                type="button"
                role="option"
                aria-selected={current}
                data-strategy={name}
                onMouseEnter={() => setCursor(index)}
                onClick={() => choose(index)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left font-mono text-xs transition-colors',
                  index === cursor ? 'bg-accent text-foreground' : 'text-muted-foreground hover:bg-accent/50'
                )}
              >
                {current ? <Check className="h-3 w-3 shrink-0 text-primary" /> : <span className="w-3 shrink-0" />}
                <span className="truncate">{name}</span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
