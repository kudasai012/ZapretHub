/**
 * Как оценивается результат проверки сайтов.
 *
 * Одно и то же правило считает и главный процесс (он выбирает победителя
 * прогона), и интерфейс (он рисует проценты и раскладку рейтинга). Раньше
 * правило было только в интерфейсе, и главный процесс выбирал стратегию по
 * своим подсчётам — расхождение было делом времени.
 *
 * Главное правило: **сайт открылся, если ответил по HTTP**. Пинг сюда не
 * входит. Пинг отвечает ICMP — им меряют, жив ли канал, и он не зависит от
 * того, пропускает ли провайдер страницу. Ровно из-за этого диагностика раньше
 * объявляла стратегию хорошей: сайты не открывались, зато пинговались.
 *
 * Цели вида «PING:адрес» — исключение: там просили пинг, значит, судим по нему.
 */
import type { DiagnosticsTargetResult } from './contract'

/** Открылся ли сайт по результату проверки. */
export function targetOk(result: DiagnosticsTargetResult): boolean {
  // HTTP проверялся и не ответил — сайт закрыт, каким бы пинг ни был.
  if (result.httpOk !== null) return result.httpOk === true
  // HTTP не проверялся (цель вида PING:) — судим по пингу.
  return result.pingOk === true
}

/** Итог по стратегии: сколько сайтов открылось и как быстро. */
export interface StrategyScore {
  /** Сколько целей открылось. */
  ok: number
  /** Сколько целей проверяли. */
  total: number
  /** Процент открывшихся. */
  percent: number
  /** Среднее время ответа, миллисекунды. Ноль — ping не меряли. */
  avgMs: number
  /** Сколько сайтов не ответили по HTTP вовсе (28, 35, 54 — закрыты). */
  broken: number
}

export function scoreStrategy(results: DiagnosticsTargetResult[] | undefined): StrategyScore {
  if (!results || results.length === 0) {
    return { ok: 0, total: 0, percent: 0, avgMs: 0, broken: 0 }
  }
  const ok = results.filter(targetOk).length
  const pings = results
    .map((item) => item.pingMs)
    .filter((value): value is number => value !== null && Number.isFinite(value))
  const avgMs = pings.length > 0 ? pings.reduce((sum, value) => sum + value, 0) / pings.length : 0
  const broken = results.filter(
    (item) => item.httpOk === false && (item.httpCode === 28 || item.httpCode === 35 || item.httpCode === 54)
  ).length
  return {
    ok,
    total: results.length,
    percent: Math.round((ok / results.length) * 100),
    avgMs,
    broken
  }
}

/**
 * Место стратегии в рейтинге: меньше — лучше.
 *
 * Сначала доля открывшихся сайтов, потом их число, потом скорость ответа. При
 * полном равенстве вперёд уходит та, что поменьше «сломала» сайтов: стратегия,
 * у которой часть сайтов отдала 403, хуже той, что ответила всем по-настоящему.
 */
export function rankStrategy(results: DiagnosticsTargetResult[] | undefined): number {
  const score = scoreStrategy(results)
  return -score.percent * 1000 - score.ok * 10 + Math.min(9, Math.round(score.avgMs / 100)) + score.broken
}

/** Лучшая стратегия из проверенных: та, что открыла больше сайтов. */
export function pickWinner(
  results: Record<string, DiagnosticsTargetResult[]>,
  order: string[]
): string | null {
  let winner: string | null = null
  let bestRank = Number.POSITIVE_INFINITY
  for (const name of order) {
    const list = results[name]
    if (!list || list.length === 0) continue
    const rank = rankStrategy(list)
    if (rank < bestRank) {
      bestRank = rank
      winner = name
    }
  }
  return winner
}
