import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Info,
  Loader2,
  Play,
  RotateCcw,
  ScrollText,
  Stethoscope,
  Wrench,
  X
} from 'lucide-react'
import type { AppConfig, DiagnosticsTargetResult, SysCheck } from '@shared/contract'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { StatusDot } from '@/components/status-dot'
import { cn, formatMs } from '@/lib/utils'
import { scoreStrategy, targetOk } from '@shared/scoring'
import { useAction, useDiagnostics, useT } from '@/hooks/use-hub'
import { toast } from '@/hooks/use-toast'

/**
 * Порог «быстрого ответа», миллисекунды.
 *
 * Им же рисуется цвет отрезка графика, и он же назван в подписи: одно число
 * на всё, чтобы подпись не расходилась с картинкой.
 */
/**
 * Провайдеры зашифрованного DNS.
 *
 * В главный процесс уходит только id: адрес знает он один, чтобы список не
 * разошёлся между окнами.
 */
const DOH_CHOICES: { id: string; name: string }[] = [
  { id: 'cloudflare', name: 'Cloudflare' },
  { id: 'google', name: 'Google' },
  { id: 'adguard', name: 'AdGuard DNS' }
]

/** Подписи: ключ и, если нужно, подстановки. */
type Translate = (key: string, params?: Record<string, string | number>) => string

const SLOW_ANSWER_MS = 300

/** Состояние одного отрезка графика. */
type SegmentState = 'fast' | 'slow' | 'fail' | 'unknown'

/**
 * Страница диагностики.
 *
 * Прогоняет стратегии по очереди: поднимает winws с очередной стратегией,
 * проверяет каждый сайт из списка, гасит winws. Текущая стратегия
 * восстанавливается в конце — прогон ничего не ломает.
 *
 * Стратегия показана строкой, а не карточкой: по одной в ряд, и в строке всё
 * важное — место в рейтинге, итог одной фразой и полоска из отрезков, где
 * каждый отрезок — одна проверка. Подробности раскрываются кнопкой, чтобы
 * результат можно было убрать с глаз, когда он уже прочитан.
 */
export function DiagnosticsPage({
  config,
  zapret,
  run
}: {
  config: AppConfig
  zapret: { installed: boolean; strategies: string[]; strategy: string } | null
  run: ReturnType<typeof useDiagnostics>
}) {
  const t = useT(config.general.language)
  const action = useAction(t)
  // Прогон идёт в главном процессе и переживает переходы между разделами:
  // состояние приходит событиями, а не живёт в памяти этой страницы. Ушёл с
  // раздела и вернулся — прогон на месте, и второй раз его не запустить.
  const { results, busy, strategy: running, done, total, merge } = run
  const [targets, setTargets] = useState<string[]>([])
  // выбранные для прогона стратегии: пустой набор = гоняем все
  const [selected, setSelected] = useState<string[]>([])
  // у каких стратегий раскрыт журнал проверки
  const [opened, setOpened] = useState<string[]>([])

  useEffect(() => {
    let alive = true
    void window.hub.diagnostics.targets().then((value) => {
      if (alive) setTargets(value)
    })
    return () => {
      alive = false
    }
  }, [])

  const testOne = useCallback(
    async (strategy: string) => {
      // Одна стратегия проверяется той же очередью, что и весь набор: строка
      // из одного элемента. И перезапуск обхода, и возврат прежней стратегии,
      // и рассылка результатов остаются одними и теми же.
      await action(window.hub.diagnostics.runQueue([strategy]), {})
    },
    [action]
  )

  /**
   * Прогон выбранных стратегий по очереди.
   *
   * Каждую стратегию проверяем отдельным вызовом: главный процесс поднимает
   * winws, мерит сайты и гасит его, и так для каждой. Между стратегиями
   * прежняя настройка возвращается на место, поэтому прогон ничего не ломает.
   */
  const testSelected = async () => {
    const queue = selected.length > 0 ? selected : zapret?.strategies ?? []
    if (queue.length === 0) return
    const value = await action(window.hub.diagnostics.runQueue(queue), {})
    if (!value || value.busy) return
    if (value.winner && value.applied) {
      toast({ title: t('diag.chosen', { name: value.winner }), variant: 'success' })
    }
  }

  /** Переключает стратегию в наборе для прогона. */
  const toggleSelected = (name: string) => {
    setSelected((prev) => (prev.includes(name) ? prev.filter((item) => item !== name) : [...prev, name]))
  }

  /** Все стратегии сразу: и выбрать, и снять выбор. */
  const toggleAll = () => {
    const all = zapret?.strategies ?? []
    setSelected((prev) => (prev.length === all.length ? [] : [...all]))
  }

  /** Раскрыть или убрать подробности по стратегии. */
  const toggleDetails = (name: string) => {
    setOpened((prev) => (prev.includes(name) ? prev.filter((item) => item !== name) : [...prev, name]))
  }

  /**
   * Порядок стратегии в рейтинге: меньше — лучше.
   *
   * Сначала доля открывшихся сайтов, потом их количество, потом скорость
   * ответа: при равном счёте работает та, что отвечает быстрее.
   */
  /**
   * Среднее время ответа: им разводим стратегии с одинаковым счётом.
   *
   * Подсчёт открывшихся сайтов — общий с главным процессом (@shared/scoring),
   * иначе экран и выбор победителя разошлись бы.
   */
  const averageMs = (list: DiagnosticsTargetResult[] | undefined): number => {
    const value = scoreStrategy(list)
    return value.avgMs > 0 ? value.avgMs : Number.MAX_SAFE_INTEGER
  }

  const canEdit = config.zapret.editTargets

  /* Правка выключена, а человек щёлкает в поле: молчать нельзя — непонятно,
     почему текст не меняется. Объясняем, где включить, и не чаще раза в
     несколько секунд, чтобы два события одного щелчка не дали два сообщения. */
  const lockedHintAt = useRef(0)
  const warnLocked = () => {
    if (canEdit) return
    const now = Date.now()
    if (now - lockedHintAt.current < 6000) return
    lockedHintAt.current = now
    toast({
      title: t('diag.targets_locked_toast'),
      description: t('diag.targets_locked_toast_hint'),
      variant: 'warning'
    })
  }

  if (!zapret) return null

  const tested = Object.keys(results)

  /**
   * Рейтинг стратегий: сначала те, что открыли больше сайтов, при равенстве —
   * те, что ответили быстрее. Непроверенные уходят в конец.
   */
  const ranked = [...zapret.strategies].sort((a, b) => {
    const left = results[a]
    const right = results[b]
    if (!left && !right) return zapret.strategies.indexOf(a) - zapret.strategies.indexOf(b)
    if (!left) return 1
    if (!right) return -1
    const sa = scoreStrategy(left)
    const sb = scoreStrategy(right)
    if (sb.percent !== sa.percent) return sb.percent - sa.percent
    if (sb.ok !== sa.ok) return sb.ok - sa.ok
    return averageMs(left) - averageMs(right)
  })

  const best = tested
    .map((name) => ({ name, ...scoreStrategy(results[name]) }))
    .sort((a, b) => b.percent - a.percent || b.ok - a.ok)[0]
  const bestMs = best ? averageMs(results[best.name]) : 0

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{t('diag.title')}</h1>
        <p className="text-sm text-muted-foreground">{t('diag.subtitle')}</p>
      </header>

      {!zapret.installed ? (
        <Card>
          <CardContent className="p-5">
            <p className="text-sm text-warning">{t('diag.not_installed')}</p>
          </CardContent>
        </Card>
      ) : null}

      {/* Итог прогона: одна карточка, которую понимают без чтения таблицы. */}
      {best && best.percent > 0 ? (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-4 p-5">
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-muted-foreground">{t('diag.best_choice')}</p>
              <p className="truncate text-lg font-semibold">{best.name}</p>
              <p className="text-sm text-muted-foreground">
                {t('diag.best_toast', { name: best.name, percent: best.percent })}
              </p>
            </div>
            <div className="flex flex-col items-end gap-1">
              <Badge variant="success">{best.percent}%</Badge>
              <span className="text-xs text-muted-foreground">
                {Number.isFinite(bestMs) ? t('diag.best_card_ms', { ms: formatMs(Math.round(bestMs)) }) : ''}
              </span>
            </div>
            {zapret.strategy === best.name ? (
              <Badge variant="muted">{t('diag.best_card_note')}</Badge>
            ) : (
              <Button
                size="sm"
                onClick={() =>
                  void action(window.hub.zapret.setStrategy(best.name), {
                    success: t('diag.chosen', { name: best.name })
                  })
                }
              >
                {t('diag.choose')}
              </Button>
            )}
          </CardContent>
        </Card>
      ) : null}

      <SystemCard t={t} />

      {/* Цели проверки */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t('diag.targets_title')}</CardTitle>
          <CardDescription className="text-xs">{t('diag.targets_hint')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {canEdit ? (
            <Badge variant="success" className="gap-1.5">
              <Check className="h-3 w-3" />
              {t('diag.targets_unlocked')}
            </Badge>
          ) : null}

          {/* Размер поля не меняется: ручка для протяжки только мешала —
              список длинный, и поле растягивали вместо того, чтобы прокрутить. */}
          <textarea
            value={targets.join('\n')}
            onChange={(event) => setTargets(event.target.value.split('\n'))}
            onFocus={warnLocked}
            onClick={warnLocked}
            readOnly={!canEdit}
            spellCheck={false}
            aria-readonly={!canEdit}
            className={cn(
              'h-40 w-full resize-none overflow-y-auto rounded-md border border-input bg-background p-3 font-mono text-xs text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
              !canEdit && 'cursor-not-allowed bg-muted/30 text-muted-foreground'
            )}
          />

          <p className="text-xs text-muted-foreground">
            {canEdit ? t('diag.targets_unlock_hint') : t('diag.targets_locked')}
          </p>

          <div className="flex flex-wrap gap-2">
            {/* Кнопка есть только тогда, когда сохранение возможно: серая
                кнопка, которая ничего не делает, только сбивала с толку. */}
            {canEdit ? (
              <Button
                size="sm"
                onClick={() =>
                  void action(window.hub.diagnostics.saveTargets(targets), {
                    success: t('diag.targets_saved'),
                    hint: t('diag.targets_saved_hint')
                  })
                }
              >
                {t('common.save')}
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                void action(window.hub.diagnostics.probeAll(), {}).then((value) => {
                  if (!value) return
                  merge(t('diag.probe'), value.results)
                  toast({
                    title: value.anyOk ? t('diag.ok') : t('diag.no_targets'),
                    variant: value.anyOk ? 'success' : 'warning'
                  })
                })
              }
            >
              <Play className="h-3.5 w-3.5" />
              {t('diag.probe')}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Стратегии */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-xs font-semibold text-muted-foreground">{t('diag.strategies')}</h2>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">
              {t('diag.tested_count', { count: tested.length })}
            </span>
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={toggleAll}>
              {selected.length === zapret.strategies.length
                ? t('diag.deselect_all')
                : t('diag.select_all')}
            </Button>
          </div>
        </div>

        {/* Прогон набора: стратегии проверяются по очереди, потом выстраиваются
            по результату, и лучшая применяется сама. */}
        <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/20 p-3">
          <Checkbox
            id="select-all"
            checked={selected.length === zapret.strategies.length && zapret.strategies.length > 0}
            onCheckedChange={toggleAll}
          />
          <Label htmlFor="select-all" className="text-sm">
            {t('diag.test_selected')}
          </Label>
          <span className="text-xs text-muted-foreground">
            {selected.length > 0
              ? t('diag.selected_count', { count: selected.length })
              : t('diag.select_hint')}
          </span>
          {/* Ход прогона. Он идёт в главном процессе, поэтому уход с раздела
              его не рвёт, а на экране видно, что прогон идёт прямо сейчас. */}
          {busy && total > 0 ? (
            <span className="text-xs text-muted-foreground">
              {t('diag.progress_count', { done, total })}
            </span>
          ) : null}
          <div className="flex-1" />
          {busy ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void action(window.hub.diagnostics.stop(), { success: t('diag.stopped_run') })}
            >
              <X className="h-3.5 w-3.5" />
              {t('diag.stop_run')}
            </Button>
          ) : null}
          <Button size="sm" onClick={() => void testSelected()} disabled={busy || !zapret.installed}>
            {running ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            {running ?? t('diag.run_selected')}
          </Button>
        </div>

        {/* Как читать полоску: одна расшифровка на весь список, а не подпись
            под каждой стратегией. */}
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          <span>{t('diag.legend')}:</span>
          <span className="inline-flex items-center gap-1.5">
            <i className="h-2 w-4 rounded-sm bg-success" />
            {t('diag.legend_fast')}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i className="h-2 w-4 rounded-sm bg-warning" />
            {t('diag.legend_slow')}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i className="h-2 w-4 rounded-sm bg-destructive" />
            {t('diag.legend_none')}
          </span>
        </p>
        <p className="text-[11px] text-muted-foreground">{t('diag.legend_note')}</p>

        {/* Строки стратегий */}
        <div className="overflow-hidden rounded-md border">
          {ranked.map((name, index) => (
            <StrategyRow
              key={name}
              name={name}
              index={index}
              tested={results[name]}
              running={running === name}
              current={zapret.strategy === name}
              leader={Boolean(best) && best.name === name && best.percent > 0}
              picked={selected.includes(name)}
              detailsOpen={opened.includes(name)}
              busy={busy}
              disabled={!zapret.installed}
              onPick={() => toggleSelected(name)}
              onTest={() => void testOne(name)}
              onToggleDetails={() => toggleDetails(name)}
              t={t}
            />
          ))}
        </div>
      </section>
    </div>
  )
}

/**
 * Одна стратегия — одна строка.
 *
 * В строке: галочка набора, место в рейтинге, имя, итог одной фразой,
 * полоска из отрезков (по отрезку на проверку) и три кнопки — выбрать,
 * подробности, проверить заново. Подробности раскрываются под строкой и
 * убираются так же: результат должен быть возможно убрать с глаз.
 */
function StrategyRow({
  name,
  index,
  tested,
  running,
  current,
  leader,
  picked,
  detailsOpen,
  busy,
  disabled,
  onPick,
  onTest,
  onToggleDetails,
  t
}: {
  name: string
  index: number
  tested: DiagnosticsTargetResult[] | undefined
  running: boolean
  current: boolean
  leader: boolean
  picked: boolean
  detailsOpen: boolean
  busy: boolean
  disabled: boolean
  onPick: () => void
  onTest: () => void
  onToggleDetails: () => void
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  const ok = tested ? tested.filter(targetOk).length : 0
  const total = tested?.length ?? 0
  const percent = total > 0 ? Math.round((ok / total) * 100) : 0
  const pings = (tested ?? []).map((item) => item.pingMs).filter((value): value is number => value !== null)
  const ms = pings.length > 0 ? Math.round(pings.reduce((sum, value) => sum + value, 0) / pings.length) : null

  const segments: SegmentState[] = (tested ?? []).map((item) => {
    if (!targetOk(item)) return 'fail'
    if (item.pingMs === null) return 'fast'
    return item.pingMs > SLOW_ANSWER_MS ? 'slow' : 'fast'
  })

  return (
    <div className={cn('border-b last:border-b-0', current && 'bg-muted/30')}>
      <div className="flex flex-wrap items-center gap-3 px-3 py-2.5">
        <Checkbox
          id={`pick-${name}`}
          checked={picked}
          onCheckedChange={onPick}
          aria-label={name}
          className="shrink-0"
        />
        <Label htmlFor={`pick-${name}`} className="sr-only">
          {name}
        </Label>

        {/* Место в рейтинге: номер после прогона, прочерк — не проверялась */}
        <span
          className="w-6 shrink-0 text-center text-xs font-semibold text-muted-foreground"
          title={t('diag.rank_hint')}
        >
          {tested ? index + 1 : '—'}
        </span>

        {leader ? <Badge variant="success">{t('diag.best_choice')}</Badge> : null}
        <StatusDot tone={running ? 'starting' : tested ? 'running' : 'stopped'} />

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={name}>
            {name}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {tested
              ? ms === null
                ? t('diag.row_summary_no_ping', { ok, total })
                : t('diag.row_summary', { ok, total, ms: formatMs(ms) })
              : t('diag.row_untested')}
          </p>
        </div>

        {tested ? (
          <Badge variant={percent >= 75 ? 'success' : percent > 0 ? 'warning' : 'destructive'}>
            {percent}%
          </Badge>
        ) : null}

        {/* Полоска из отрезков: каждый отрезок — одна проверка, поэтому видно
            не только «сколько», но и «где» стратегия подводит. */}
        <div className="flex h-1.5 w-32 shrink-0 items-stretch gap-px" title={t('diag.row_bar', { slow: SLOW_ANSWER_MS })}>
          {segments.length === 0 ? (
            <span className="h-full flex-1 rounded-sm bg-muted" />
          ) : (
            segments.map((state, position) => (
              <span
                key={`${name}-${position}`}
                className={cn(
                  'h-full flex-1 rounded-sm',
                  state === 'fast' && 'bg-success',
                  state === 'slow' && 'bg-warning',
                  state === 'fail' && 'bg-destructive',
                  state === 'unknown' && 'bg-muted'
                )}
              />
            ))
          )}
        </div>

        {current ? (
          <Badge variant="muted">{t('diag.chosen_short')}</Badge>
        ) : tested && !current ? (
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => void window.hub.zapret.setStrategy(name)}
          >
            <Check className="h-3.5 w-3.5" />
            {t('diag.choose')}
          </Button>
        ) : null}

        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={onToggleDetails}
          aria-label={detailsOpen ? t('diag.collapse_hint') : t('diag.expand_hint')}
          title={detailsOpen ? t('diag.collapse_hint') : t('diag.expand_hint')}
        >
          <ScrollText className="h-3.5 w-3.5" />
          <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', detailsOpen && 'rotate-90')} />
        </Button>

        <Button
          variant={current ? 'default' : 'outline'}
          size="sm"
          className="h-7 text-xs"
          disabled={busy || disabled}
          onClick={onTest}
        >
          {running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RotateCcw className="h-3.5 w-3.5" />
          )}
          {t('diag.test_one')}
        </Button>
      </div>

      {detailsOpen ? (
        <div className="space-y-2 border-t bg-muted/20 px-3 py-2">
          <ResultsTable results={tested ?? []} t={t} />
        </div>
      ) : null}
    </div>
  )
}

/** Коды curl, которым есть понятное объяснение. */
const EXPLAINED_CURL = [6, 7, 28, 35, 52, 54, 56, 60]

/** Что показать про проверку сайта одной строкой. */
function httpLine(result: DiagnosticsTargetResult, t: Translate): string {
  if (result.httpOk === null) return t('diag.http_skipped')
  if (result.httpStatus > 0) return t('diag.http_ok', { code: result.httpStatus })
  return result.error || t('diag.http_none')
}

/** Почему проверка сайта вышла такой — простым языком. */
function httpNote(result: DiagnosticsTargetResult, t: Translate): string {
  if (result.httpOk === null) return ''
  if (result.httpOk) return t('diag.note_http_ok')
  // ответ с кодом — не отказ соединения: сайт живой, просто ответил не тем
  if (result.httpStatus > 0) return t('diag.explain_status', { code: result.httpStatus })
  if (result.httpCode > 0) {
    return EXPLAINED_CURL.includes(result.httpCode)
      ? t(`diag.explain_${result.httpCode}`)
      : t('diag.explain_other', { code: result.httpCode })
  }
  return t('diag.explain_no_status')
}

/** Что показать про проверку связи одной строкой. */
function pingLine(result: DiagnosticsTargetResult, t: Translate): string {
  if (result.pingOk === null) return t('diag.ping_skipped')
  if (result.pingOk) return t('diag.ping_ok', { ms: formatMs(result.pingMs) })
  return t('diag.ping_none')
}

/**
 * Подробности по целям: раскрываются кнопкой и так же убираются.
 *
 * Строка цели нажимается вся: щелчок открывает разбор одной проверки — что
 * именно ответило, каким кодом и что это значит. Раньше причина отказа
 * помещалась в строку таблицы одной обрезанной надписью, и понять по ней,
 * сайт недоступен или его имя просто не находится, было нельзя.
 */
function ResultsTable({ results, t }: { results: DiagnosticsTargetResult[]; t: Translate }) {
  const [picked, setPicked] = useState<DiagnosticsTargetResult | null>(null)

  if (results.length === 0) {
    return <p className="text-xs text-muted-foreground">{t('diag.not_tested_yet')}</p>
  }

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('diag.targets_title')}</TableHead>
            <TableHead className="w-20 text-center">HTTP</TableHead>
            <TableHead className="w-20 text-center">PING</TableHead>
            <TableHead className="w-24 text-right">{t('diag.avg')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {results.map((result) => (
            <TableRow
              key={`${result.name}-${result.address}`}
              role="button"
              tabIndex={0}
              title={t('diag.row_details')}
              onClick={() => setPicked(result)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  setPicked(result)
                }
              }}
              className="cursor-pointer transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
            >
              <TableCell className="max-w-[280px]">
                <span className="truncate-cell" title={result.address}>
                  {result.name}
                </span>
                {/* Причина отказа — прямо в строке: крестик сам по себе не говорит,
                    сайт заблокирован или стратегия вообще не встала. */}
                {result.error ? (
                  <span className="mt-0.5 block truncate text-[11px] text-destructive" title={result.error}>
                    {result.error}
                  </span>
                ) : result.httpStatus > 0 ? (
                  <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                    {t('diag.http_status', { code: result.httpStatus })}
                  </span>
                ) : null}
              </TableCell>
              <TableCell className="text-center">
                <Mark ok={result.httpOk} t={t} />
              </TableCell>
              <TableCell className="text-center">
                <Mark ok={result.pingOk} t={t} />
              </TableCell>
              <TableCell className="text-right text-xs text-muted-foreground">
                {formatMs(result.pingMs)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <TargetDialog result={picked} onClose={() => setPicked(null)} t={t} />
    </>
  )
}

/**
 * Разбор одной проверки.
 *
 * Показываем обе половины проверки отдельно — сайт и связь — и объясняем
 * отказ словами: «имя не найдено» само по себе ничего не говорит человеку,
 * а «DNS не нашёл имя» объясняет, что обход тут ни при чём.
 */
function TargetDialog({
  result,
  onClose,
  t
}: {
  result: DiagnosticsTargetResult | null
  onClose: () => void
  t: Translate
}) {
  const note = result ? httpNote(result, t) : ''
  const pingNote = result && result.pingOk === false ? t('diag.note_ping_fail') : ''

  return (
    <Dialog open={result !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="data-[state=closed]:animate-none sm:max-w-md">
        {result ? (
          <>
            <DialogHeader>
              <DialogTitle className="truncate">{result.name}</DialogTitle>
              <DialogDescription className="break-all font-mono text-xs">
                {result.address}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              <div className="flex gap-2.5">
                <span className="mt-0.5 shrink-0">
                  <Mark ok={result.httpOk} t={t} />
                </span>
                <div className="min-w-0 space-y-1">
                  <p className="text-xs text-muted-foreground">{t('diag.detail_http')}</p>
                  <p className="text-sm">{httpLine(result, t)}</p>
                  {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
                </div>
              </div>

              <div className="flex gap-2.5">
                <span className="mt-0.5 shrink-0">
                  <Mark ok={result.pingOk} t={t} />
                </span>
                <div className="min-w-0 space-y-1">
                  <p className="text-xs text-muted-foreground">{t('diag.detail_ping')}</p>
                  <p className="text-sm">{pingLine(result, t)}</p>
                  {pingNote ? <p className="text-xs text-muted-foreground">{pingNote}</p> : null}
                </div>
              </div>

              {result.pingOk ? (
                <p className="text-xs text-muted-foreground">
                  {t('diag.detail_avg')}: {formatMs(result.pingMs)}
                </p>
              ) : null}
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={onClose}>
                {t('common.close')}
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

/** Галочка, крестик или прочерк — три состояния проверки. */
function Mark({
  ok,
  t
}: {
  ok: boolean | null
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  if (ok === null) {
    return <span className="text-xs text-muted-foreground">—</span>
  }
  if (ok) {
    return (
      <span title={t('diag.ok')} className="inline-flex text-success">
        <Check className="h-4 w-4" strokeWidth={2.5} />
      </span>
    )
  }
  return (
    <span title={t('diag.no_access')} className="inline-flex text-destructive">
      <X className="h-4 w-4" strokeWidth={2.5} />
    </span>
  )
}

/**
 * Диагностика системы: проверки из `service.bat` пакета zapret.
 *
 * Зачем отдельным блоком. Прежняя диагностика умела только «отвечают ли сайты»,
 * а причина чаще всего не в стратегии: включён системный прокси, стоит Adguard,
 * в системе осталась служба WinDivert от чужой копии winws, пакет распакован в
 * папку с кириллицей. Человек этого не видит и идёт перезагружать компьютер.
 *
 * Там, где причина чинится кнопкой, кнопка тут же и есть: удалить службу
 * WinDivert, снять чужой обход, включить TCP-метки, почистить кэш Discord.
 */
function SystemCard({ t }: { t: (key: string, params?: Record<string, string | number>) => string }) {
  const [busy, setBusy] = useState(false)
  const [checks, setChecks] = useState<SysCheck[] | null>(null)
  const [fixing, setFixing] = useState<string | null>(null)
  const [dohProvider, setDohProvider] = useState(DOH_CHOICES[0].id)
  /** Результат проверки занимает пол-экрана: его можно убрать крестиком. */
  const [open, setOpen] = useState(true)

  const run = async () => {
    setBusy(true)
    try {
      setChecks(await window.hub.sysdiag.run())
      setOpen(true)
    } catch {
      setChecks([])
    } finally {
      setBusy(false)
    }
  }

  const fix = async (id: NonNullable<SysCheck['fix']>, option?: string) => {
    setFixing(id)
    try {
      const result = await window.hub.sysdiag.fix(id, option)
      toast({
        title: result.ok
          ? t('sys.fixed', { message: result.message })
          : t('sys.fix_failed', { message: result.message }),
        variant: result.ok ? 'success' : 'destructive'
      })
      // После починки проверяем заново: человек должен видеть, что строка
      // позеленела, а не верить нам на слово.
      setChecks(await window.hub.sysdiag.run())
      // Свёрнутый результат после починки открываем: человек нажал «починить»
      // именно затем, чтобы увидеть, что стало.
      setOpen(true)
    } finally {
      setFixing(null)
    }
  }

  const problems = (checks ?? []).filter((check) => check.status === 'fail' || check.status === 'warn')

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t('sys.title')}</CardTitle>
        <CardDescription className="text-xs">{t('sys.hint')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => void run()} disabled={busy}>
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Stethoscope className="h-3.5 w-3.5" />
            )}
            {busy ? t('sys.checking') : checks ? t('sys.again') : t('sys.run')}
          </Button>
          {checks ? (
            <span className="text-xs text-muted-foreground">
              {problems.length === 0 ? t('sys.nothing') : t('sys.problems', { count: problems.length })}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">{t('sys.empty')}</span>
          )}

          {/* Крестик убирает сам список проверок: он длинный и нужен
              человеку один раз, а заголовок с кнопкой остаётся на месте. */}
          {checks && checks.length > 0 ? (
            <Button
              variant="ghost"
              size="icon"
              className="ml-auto h-7 w-7 shrink-0"
              onClick={() => setOpen(!open)}
              aria-expanded={open}
              aria-label={open ? t('sys.collapse') : t('sys.expand')}
              title={open ? t('sys.collapse') : t('sys.expand')}
            >
              {open ? <X className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </Button>
          ) : null}
        </div>

        {checks && checks.length > 0 && open ? (
          <div className="divide-y rounded-md border">
            {checks.map((check) => {
              // Настройка зашифрованного DNS уже записана: либо подтверждена
              // («ок»), либо записана в браузер, который её мог не принять.
              const dohWritten = check.status === 'ok' || check.detail !== ''
              return (
                <div key={check.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                  <CheckIcon status={check.status} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">{t(`sys.${check.id}`)}</p>
                    <p className="text-xs text-muted-foreground">
                      {check.id === 'doh' && check.detail !== ''
                        ? // У строки про зашифрованный DNS список браузеров
                          // важнее подсказки: там же помечено, какой браузер
                          // настройку мог не принять.
                          check.detail
                        : check.status === 'ok' || check.status === 'info'
                          ? t(`sys.${check.id}.hint`)
                          : check.detail || t(`sys.${check.id}.hint`)}
                      </p>
                  </div>
                  {check.fix ? (
                    check.id === 'doh' ? (
                      <div className="flex items-center gap-2">
                        {dohWritten ? null : (
                          <Select value={dohProvider} onValueChange={setDohProvider}>
                            <SelectTrigger className="h-7 w-[9.5rem] text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {DOH_CHOICES.map((item) => (
                                <SelectItem key={item.id} value={item.id} className="text-xs">
                                  {item.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs"
                          disabled={fixing !== null}
                          onClick={() =>
                            void fix(check.fix as NonNullable<SysCheck['fix']>, dohWritten ? 'off' : dohProvider)
                          }
                        >
                          {fixing === check.fix ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Wrench className="h-3.5 w-3.5" />
                          )}
                          {fixing === check.fix ? t('sys.fixing') : dohWritten ? t('sys.doh_off') : t('sys.doh_on')}
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        disabled={fixing !== null}
                        onClick={() => void fix(check.fix as NonNullable<SysCheck['fix']>)}
                      >
                        {fixing === check.fix ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Wrench className="h-3.5 w-3.5" />
                        )}
                        {fixing === check.fix ? t('sys.fixing') : t('sys.fix')}
                      </Button>
                    )
                  ) : null}
                </div>
              )
            })}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/** Значок проверки: зелёная галочка, жёлтый восклицательный, красный крест. */
function CheckIcon({ status }: { status: SysCheck['status'] }) {
  if (status === 'ok') {
    return (
      <span className="inline-flex text-success">
        <Check className="h-4 w-4" strokeWidth={2.5} />
      </span>
    )
  }
  if (status === 'warn') {
    return (
      <span className="inline-flex text-warning">
        <AlertTriangle className="h-4 w-4" strokeWidth={2.5} />
      </span>
    )
  }
  if (status === 'fail') {
    return (
      <span className="inline-flex text-destructive">
        <X className="h-4 w-4" strokeWidth={2.5} />
      </span>
    )
  }
  return (
    <span className="inline-flex text-muted-foreground">
      <Info className="h-4 w-4" strokeWidth={2.5} />
    </span>
  )
}
