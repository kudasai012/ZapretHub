import { useEffect, useState } from 'react'
import { Download, ExternalLink, FolderOpen, RefreshCw, Trash2 } from 'lucide-react'
import type { AppConfig, ComponentKey, HomeState, UpdateInfo } from '@shared/contract'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import appIcon from '@/assets/icon.png'
import { useAction, useT } from '@/hooks/use-hub'
import { toast } from '@/hooks/use-toast'

/** Репозиторий самой программы — его и показываем в настройках. */
const REPO_URL = 'https://github.com/kudasai012/ZapretHub'

/** Сколько ждать, пока человек прочитает предупреждение. */
const CONFIRM_DELAY_MS = 5000

/**
 * Страница настроек: общие, автозапуск, для опытных, обновления, расположение
 * и сведения о программе.
 */
export function SettingsPage({
  config,
  home,
  onShowRelease
}: {
  config: AppConfig
  home: HomeState | null
  onShowRelease: () => void
}) {
  const t = useT(config.general.language)
  const action = useAction(t)
  const [appVersion, setAppVersion] = useState('')
  /** Удаление программы: есть ли деинсталлятор и открыт ли вопрос. */
  const [canUninstall, setCanUninstall] = useState(false)
  const [askUninstall, setAskUninstall] = useState(false)
  // секунды, которые осталось ждать: удаление необратимо, кнопка открывается
  // не сразу, чтобы решение не принималось одним щелчком
  const [uninstallLeft, setUninstallLeft] = useState(0)

  useEffect(() => {
    void window.hub.app.version().then(setAppVersion)
  }, [])

  useEffect(() => {
    void window.hub.app.uninstallInfo().then((info) => setCanUninstall(info.path !== ''))
  }, [])

  useEffect(() => {
    if (!askUninstall) {
      setUninstallLeft(0)
      return
    }
    setUninstallLeft(CONFIRM_DELAY_MS / 1000)
    const started = Date.now()
    const timer = setInterval(() => {
      const rest = Math.max(0, CONFIRM_DELAY_MS - (Date.now() - started))
      setUninstallLeft(Math.ceil(rest / 1000))
      if (rest <= 0) clearInterval(timer)
    }, 250)
    return () => clearInterval(timer)
  }, [askUninstall])

  /**
   * Удалить программу.
   *
   * Деинсталлятор запускаем отсоединённо, а программу закрываем чуть позже:
   * так он не задаёт лишний вопрос про запущенную копию. Компоненты,
   * настройки и журналы убирает сам деинсталлятор.
   */
  const uninstall = async () => {
    setAskUninstall(false)
    const result = await window.hub.app.uninstall()
    if (!result.ok) {
      toast({ title: t('common.error'), description: result.reason, variant: 'destructive' })
    }
  }

  const save = (patch: Record<string, unknown>) => void action(window.hub.config.save(patch), {})

  /**
   * Смена языка.
   *
   * Язык — это не только подписи на экране, он уходит и в настройки
   * компонентов, поэтому интерфейс не перерисовываем на месте, а сохраняем
   * выбор и перезапускаем программу: новый процесс сразу прочитает новое
   * значение. Без перезапуска часть надписей осталась бы старой.
   */
  const changeLanguage = (value: string) => {
    void (async () => {
      const next = await window.hub.config.save({ general: { language: value as 'ru' | 'en' } })
      const restarting = next.general.language === 'ru' ? 'Перезапуск…' : 'Restarting…'
      toast({ title: t('set.language_restart'), description: restarting, variant: 'success' })
      try {
        await window.hub.app.restart()
      } catch (error) {
        // выбор уже сохранён: если перезапуск не удался, язык применится
        // при следующем запуске, поэтому это предупреждение, а не ошибка
        toast({
          title: t('set.language_restart'),
          description: error instanceof Error ? error.message : String(error),
          variant: 'warning'
        })
      }
    })()
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{t('set.title')}</h1>
        <p className="text-sm text-muted-foreground">
          {t('set.language')} · {t('set.autostart')}
        </p>
      </header>

      {/* Общие */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t('set.general')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="language">{t('set.language')}</Label>
            <Select value={config.general.language} onValueChange={changeLanguage}>
              <SelectTrigger id="language" className="max-w-[220px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ru">Русский</SelectItem>
                <SelectItem value="en">English</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t('set.language_restart')}</p>
          </div>

          <Separator />

          <div className="space-y-1">
            <ToggleRow
              label={t('set.minimize_to_tray')}
              checked={config.general.minimizeToTray}
              onChange={(value) => save({ general: { minimizeToTray: value } })}
            />
            <ToggleRow
              label={t('set.start_minimized')}
              checked={config.general.startMinimized}
              onChange={(value) => save({ general: { startMinimized: value } })}
            />
            <ToggleRow
              label={t('set.check_on_start')}
              checked={config.general.checkUpdatesOnStart}
              onChange={(value) => save({ general: { checkUpdatesOnStart: value } })}
            />
            <ToggleRow
              label={t('settings.stop_on_quit')}
              checked={config.general.stopComponentsOnQuit}
              onChange={(value) => save({ general: { stopComponentsOnQuit: value } })}
            />
          </div>
          <p className="text-xs text-muted-foreground">{t('settings.stop_on_quit_hint')}</p>
        </CardContent>
      </Card>

      {/* Автозапуск */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t('set.autostart')}</CardTitle>
          <CardDescription className="text-xs">{t('set.autostart_hint')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <ToggleRow
              label={t('set.autostart_enable')}
              checked={config.autostart.enabled}
              onChange={(value) => save({ autostart: { enabled: value } })}
            />
            <ToggleRow
              label={t('set.autostart_zapret')}
              checked={config.autostart.startZapret}
              onChange={(value) => save({ autostart: { startZapret: value } })}
            />
            <ToggleRow
              label={t('set.autostart_tgws')}
              checked={config.autostart.startTgws}
              onChange={(value) => save({ autostart: { startTgws: value } })}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="delay">{t('set.autostart_delay')}</Label>
            <Input
              id="delay"
              type="number"
              min={0}
              max={600}
              className="max-w-[140px]"
              value={config.autostart.delaySeconds}
              onChange={(event) => save({ autostart: { delaySeconds: Number(event.target.value) } })}
            />
          </div>
        </CardContent>
      </Card>

      {/* Для опытных */}
      <AdvancedCard config={config} t={t} save={save} />

      {/* Обновления */}
      <UpdatesCard home={home} appVersion={appVersion} t={t} action={action} onShowRelease={onShowRelease} />

      {/* Расположение */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t('set.paths')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void action(window.hub.shell.openPath('components'), {})}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              {t('set.components_dir')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void action(window.hub.shell.openPath('logs'), {})}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              {t('set.logs_dir')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void window.hub.shell.openUrl(REPO_URL)}
            >
              <ExternalLink className="h-3.5 w-3.5" />
              GitHub
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* О программе — последним: это сведения, а не то, чем пользуются каждый день. */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t('about.title')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Удаление стоит напротив названия и версии: человек смотрит,
              что за программа стоит, и тут же видит, как её убрать. */}
          <div className="flex flex-wrap items-center gap-3">
            <img
              src={appIcon}
              alt=""
              width={44}
              height={44}
              className="h-11 w-11 shrink-0 rounded-md border"
            />
            <div className="min-w-0 flex-1 space-y-0.5">
              <p className="text-sm font-semibold">Zapret Hub</p>
              <p className="text-xs text-muted-foreground">
                {t('set.version')}: <span className="text-foreground">{appVersion || '…'}</span>
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              disabled={!canUninstall}
              onClick={() => setAskUninstall(true)}
              title={canUninstall ? t('set.uninstall_hint') : t('set.uninstall_missing')}
            >
              <Trash2 className="h-3.5 w-3.5" />
              {t('set.uninstall')}
            </Button>
          </div>

          <Separator />

          <div className="space-y-3 text-xs">
            <div className="space-y-0.5">
              <p className="text-muted-foreground">{t('set.author')}</p>
              <p className="text-foreground">kudasai012</p>
            </div>
            <div className="space-y-0.5">
              <p className="text-muted-foreground">{t('set.components_authors')}</p>
              <p className="text-foreground">Flowseal · zapret-discord-youtube</p>
              <p className="text-foreground">Flowseal · tg-ws-proxy</p>
            </div>
          </div>

          <Button variant="outline" size="sm" onClick={() => void window.hub.shell.openUrl(REPO_URL)}>
            <ExternalLink className="h-3.5 w-3.5" />
            {t('set.open_repo')}
          </Button>

          <p className="text-xs text-muted-foreground">{t('set.licence')}</p>
        </CardContent>
      </Card>

      {/* Удаление программы: вопрос задаём здесь, а не средствами Windows.
          Деинсталлятор стирает настройки, журналы и скачанные компоненты —
          человек должен это прочитать до того, как нажмёт. */}
      <Dialog open={askUninstall} onOpenChange={setAskUninstall}>
        <DialogContent className="data-[state=closed]:animate-none">
          <DialogHeader>
            <DialogTitle>{t('set.uninstall')}</DialogTitle>
            <DialogDescription className="whitespace-pre-line">
              {t('set.uninstall_confirm')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAskUninstall(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              disabled={uninstallLeft > 0}
              onClick={() => void uninstall()}
            >
              {uninstallLeft > 0 ? `${uninstallLeft} ${t('common.sec_short')}` : t('set.uninstall')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
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

type Translate = (key: string, params?: Record<string, string | number>) => string

/**
 * Настройки для опытных: правка целей диагностики.
 *
 * Включение спрашивает подтверждение с задержкой: ошибка в списке сайтов
 * делает рабочую стратегию нерабочей на бумаге, и разбираться в этом потом
 * дольше, чем прочитать предупреждение.
 */
function AdvancedCard({
  config,
  t,
  save
}: {
  config: AppConfig
  t: Translate
  save: (patch: Record<string, unknown>) => void
}) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  // секунды, которые осталось ждать: раньше на кнопке просто висело «5 с», и
  // непонятно было, идёт отсчёт или программа зависла
  const [left, setLeft] = useState(0)

  useEffect(() => {
    if (!confirmOpen) {
      setLeft(0)
      return
    }
    setLeft(CONFIRM_DELAY_MS / 1000)
    const started = Date.now()
    // четверть секунды: цифра меняется на каждой секунде, но без заметного
    // отставания от настоящего времени
    const timer = setInterval(() => {
      const rest = Math.max(0, CONFIRM_DELAY_MS - (Date.now() - started))
      setLeft(Math.ceil(rest / 1000))
      if (rest <= 0) clearInterval(timer)
    }, 250)
    return () => clearInterval(timer)
  }, [confirmOpen])

  const waited = left === 0

  const confirm = () => {
    save({ zapret: { editTargets: true } })
    setConfirmOpen(false)
    toast({ title: t('diag.targets_unlocked'), variant: 'success' })
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t('diag.targets_confirm_title')}</CardTitle>
          <CardDescription className="text-xs">{t('diag.targets_title')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <ToggleRow
            label={t('diag.targets_unlock')}
            checked={config.zapret.editTargets}
            onChange={(value) => {
              if (value) setConfirmOpen(true)
              else save({ zapret: { editTargets: false } })
            }}
          />
          <p className="text-xs text-muted-foreground">{t('diag.targets_unlock_hint')}</p>
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        {/* Закрытие — мгновенное, без анимации ухода. С анимацией окно еще
            четверть секунды висело на экране после «Отмены», и казалось, что
            отмена не сработала, а потом всплыло какое-то окно. */}
        <DialogContent className="data-[state=closed]:animate-none">
          <DialogHeader>
            <DialogTitle>{t('diag.targets_confirm_title')}</DialogTitle>
            <DialogDescription className="whitespace-pre-line">
              {t('diag.targets_confirm_body')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={confirm} disabled={!waited}>
              {waited ? t('common.continue') : `${left} ${t('common.sec_short')}`}
            </Button>
          </DialogFooter>
          {/* Сколько ждать, видно на самой кнопке: «5 с» меняется на «Продолжить».
              Отдельной строкой про это писать не нужно — она только шумит. */}
        </DialogContent>
      </Dialog>
    </>
  )
}

/**
 * Обновления: версия каждого компонента и кнопка «Проверить» рядом с ней.
 *
 * Ни интервала, ни прокси здесь нет намеренно: проверка по умолчанию и так
 * сама по себе, а ручная — это одна кнопка. Если вышла новая версия,
 * программа спрашивает, качать ли; если всё свежее, говорит об этом.
 */
function UpdatesCard({
  home,
  appVersion,
  t,
  action,
  onShowRelease
}: {
  home: HomeState | null
  appVersion: string
  t: Translate
  action: ReturnType<typeof useAction>
  onShowRelease: () => void
}) {
  const [offer, setOffer] = useState<{ key: ComponentKey; info: UpdateInfo } | null>(null)

  const checkComponent = async (key: ComponentKey) => {
    const value = await action(window.hub.updates.check(true), {})
    if (!value) return
    const info = value.checked.find((item) => item.key === key)
    if (info) setOffer({ key, info })
    else toast({ title: t('upd.actual'), variant: 'success' })
  }

  const checkApp = async () => {
    const value = await action(window.hub.appUpdate.check(true), {})
    if (!value) return
    if (value.available && value.info) onShowRelease()
    else toast({ title: t('upd.actual'), variant: 'success' })
  }

  const download = () => {
    if (!offer) return
    void action(window.hub.updates.apply(offer.key), {
      success: t('upd.download'),
      failure: t('upd.update_failed')
    })
    setOffer(null)
  }

  const versions: { key: ComponentKey; name: string; version: string }[] = [
    { key: 'zapret', name: 'zapret-discord-youtube', version: home?.zapret.version ?? '—' },
    { key: 'tgws', name: 'tg-ws-proxy', version: home?.tgws.version ?? '—' }
  ]

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t('upd.title')}</CardTitle>
          <CardDescription className="text-xs">{t('upd.network_hint')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Тумблера «проверять обновления» здесь нет намеренно: он был и
              здесь, и в общих настройках, и включали его в двух местах,
              а работал только один. Проверка при запуске включается в общих
              настройках — там, где и остальные привычки программы. */}

          <div className="space-y-2">
            {versions.map((item) => (
              <div key={item.key} className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{item.name}</p>
                  <p className="text-xs text-muted-foreground">{item.version}</p>
                </div>
                <Button size="sm" variant="outline" onClick={() => void checkComponent(item.key)}>
                  <RefreshCw className="h-3.5 w-3.5" />
                  {t('upd.check_one')}
                </Button>
              </div>
            ))}
          </div>

          <Separator />

          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm">Zapret Hub</p>
              <p className="text-xs text-muted-foreground">{appVersion || '…'}</p>
            </div>
            <Button size="sm" variant="outline" onClick={() => void checkApp()}>
              <RefreshCw className="h-3.5 w-3.5" />
              {t('upd.check_one')}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Dialog open={offer !== null} onOpenChange={(open) => !open && setOffer(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {offer ? t('upd.new_version_title', { version: offer.info.latest }) : ''}
            </DialogTitle>
            <DialogDescription>
              {offer
                ? t('upd.new_version_body', {
                    current: versions.find((item) => item.key === offer.key)?.version ?? ''
                  })
                : ''}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOffer(null)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={download}>
              <Download className="h-3.5 w-3.5" />
              {t('upd.download')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
