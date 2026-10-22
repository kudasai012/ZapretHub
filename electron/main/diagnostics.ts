/**
 * Диагностика: проверка сайтов и поиск рабочей стратегии.
 *
 * Формат цели — как в utils/targets.txt пакета zapret:
 *   «Имя = https://хост»   — проверяем HTTP и ping
 *   «Имя = PING:адрес»     — только ping
 *   «хост» или «хост:порт» — тоже работают
 */
import type { DiagnosticsTargetResult } from '@shared/contract'
import { configStore, DEFAULT_DIAG_TARGETS } from './config'
import { httpCheck, ping } from './win32'
import { targetOk } from '@shared/scoring'

export interface ParsedTarget {
  name: string
  address: string
  /** Нужна ли проверка по HTTP. */
  http: boolean
  /** Нужна ли проверка ping. */
  ping: boolean
}

/** Разбирает одну строку списка целей. */
export function parseTarget(line: string): ParsedTarget | null {
  const text = line.trim()
  if (!text || text.startsWith('#')) return null

  let name = text
  let address = text
  const eq = text.indexOf('=')
  if (eq !== -1) {
    name = text.slice(0, eq).trim()
    address = text
      .slice(eq + 1)
      .trim()
      .replace(/^["']|["']$/g, '')
      .trim()
  }

  const pingOnly = /^PING:/i.test(address)
  let http = false
  if (pingOnly) {
    address = address.slice(5).trim()
  } else if (/^https?:\/\//i.test(address)) {
    http = true
  } else if (address.includes(':')) {
    // «хост:порт» — проверяем по HTTP на этом порту
    address = `http://${address}`
    http = true
  } else {
    address = `https://${address}`
    http = true
  }

  if (!address) return null
  return { name: name || address, address, http, ping: true }
}

export function parseTargets(lines: string[]): ParsedTarget[] {
  const result: ParsedTarget[] = []
  for (const line of lines) {
    const parsed = parseTarget(line)
    if (parsed) result.push(parsed)
  }
  return result
}

/** Список целей из конфига. */
export function targets(): ParsedTarget[] {
  const configured = configStore.get().zapret.diagTargets
  const lines = configured.length > 0 ? configured : DEFAULT_DIAG_TARGETS
  return parseTargets(lines)
}

/** Проверяет одну цель: HTTP и ping. */
export async function checkTarget(parsed: ParsedTarget): Promise<DiagnosticsTargetResult> {
  const result: DiagnosticsTargetResult = {
    name: parsed.name,
    address: parsed.address,
    httpOk: null,
    httpStatus: 0,
    httpCode: 0,
    pingOk: null,
    pingMs: null,
    error: ''
  }

  if (parsed.http) {
    const http = await httpCheck(parsed.address)
    result.httpOk = http.ok
    result.httpStatus = http.status
    result.httpCode = http.code
    if (!http.ok) result.error = http.error
  }

  // ping смотрим только для тех, кто не попросил проверять лишь ping:
  // иначе каждая строка списка тратила бы лишнюю секунду
  if (parsed.ping) {
    const host = parsed.address.replace(/^https?:\/\//i, '').replace(/[/?#].*$/, '').split(':')[0]
    const pong = await ping(host)
    result.pingOk = pong.ok
    result.pingMs = pong.ms
    if (!pong.ok && !result.error) result.error = pong.error
  }

  return result
}

/** Проверяет все цели из конфига. */
export async function checkAll(): Promise<DiagnosticsTargetResult[]> {
  const list = targets()
  const results: DiagnosticsTargetResult[] = []
  for (const target of list) {
    results.push(await checkTarget(target))
  }
  return results
}

/**
 * Отвечает ли хоть один сайт.
 *
 * Нужно, чтобы отличать «всё заблокировано» от «нет сети вообще»: если не
 * отвечает ни один сайт, программа говорит об этом прямо, а не выдаёт это за
 * блокировку.
 */
export async function probeAll(): Promise<{ anyOk: boolean; results: DiagnosticsTargetResult[] }> {
  const results = await checkAll()
  const anyOk = results.some((r) => targetOk(r))
  return { anyOk, results }
}

/**
 * Прогон одной стратегии: переключаем конфиг, запускаем zapret, проверяем
 * цели, гасим zapret.
 *
 * Стратегия проверяется на живой системе, поэтому всё идёт последовательно
 * и с паузами: фильтр WinDivert освобождает ядро не мгновенно, и без паузы
 * следующая копия winws успевала стартовать раньше и получить отказ.
 */
export const PROBE_SETTLE_SECONDS = 1500
export const START_CONFIRM_SECONDS = 800
