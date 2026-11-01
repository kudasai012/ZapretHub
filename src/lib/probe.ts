import type { DiagnosticsTargetResult } from '@shared/contract'
import { targetOk } from '@shared/scoring'

/**
 * Полоска проверки: один отрезок на цель.
 *
 * Вынесено из экрана Диагностики, потому что ту же полоску показывает и
 * главная: правила зачёта обязаны быть одни, иначе в Диагностике стратегия
 * будет «рабочей», а на главной — нет.
 */

/** Ответ дольше этого — уже медленно: отрезок желтеет. */
export const SLOW_ANSWER_MS = 300

export type SegmentState = 'fast' | 'slow' | 'fail' | 'unknown'

/** Состояние каждого отрезка: видно не только «сколько», но и «где» подводит. */
export function segmentsOf(results: DiagnosticsTargetResult[]): SegmentState[] {
  return results.map((item) => {
    if (!targetOk(item)) return 'fail'
    if (item.pingMs === null) return 'fast'
    return item.pingMs > SLOW_ANSWER_MS ? 'slow' : 'fast'
  })
}

export const SEGMENT_CLASS: Record<SegmentState, string> = {
  fast: 'bg-success',
  slow: 'bg-warning',
  fail: 'bg-destructive',
  unknown: 'bg-muted'
}

/** Итог одной строкой: сколько целей открылось и с какой скоростью отвечали. */
export function probeSummary(results: DiagnosticsTargetResult[]): {
  ok: number
  total: number
  ms: number | null
} {
  const total = results.length
  const ok = results.filter(targetOk).length
  const pings = results
    .map((item) => item.pingMs)
    .filter((value): value is number => typeof value === 'number')
  const ms =
    pings.length > 0 ? Math.round(pings.reduce((sum, value) => sum + value, 0) / pings.length) : null
  return { ok, total, ms }
}
