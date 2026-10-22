import { useCallback, useEffect, useState } from 'react'
import { Check, ChevronRight, Loader2, Play, RotateCcw, ScrollText, X } from 'lucide-react'
import type { AppConfig, DiagnosticsTargetResult } from '@shared/contract'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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

          <textarea
            value={targets.join('\n')}
            onChange={(event) => setTargets(event.target.value.split('\n'))}
            readOnly={!canEdit}
            spellCheck={false}
            aria-readonly={!canEdit}
            className={cn(
              'h-40 w-full resize-y rounded-md border border-input bg-background p-3 font-mono text-xs text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
              !canEdit && 'cursor-not-allowed bg-muted/30 text-muted-foreground'
            )}
          />

          <p className="text-xs text-muted-foreground">
            {canEdit ? t('diag.targets_unlock_hint') : t('diag.targets_locked')}
          </p>

          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={!canEdit}
              onClick={() =>
                void action(window.hub.diagnostics.saveTargets(targets), {
                  success: t('diag.targets_saved')
                })
              }
            >
              {t('common.save')}
            </Button>
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

/** Подробности по целям: раскрываются кнопкой и так же убираются. */
function ResultsTable({
  results,
  t
}: {
  results: DiagnosticsTargetResult[]
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  if (results.length === 0) {
    return <p className="text-xs text-muted-foreground">{t('diag.not_tested_yet')}</p>
  }
  return (
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
          <TableRow key={`${result.name}-${result.address}`}>
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
