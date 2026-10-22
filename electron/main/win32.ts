/**
 * Windows-обвязка: права администратора, службы, чужие процессы, реестр.
 *
 * Всё через штатные утилиты Windows (sc, taskkill, reg, PowerShell) —
 * никаких нативных модулей вроде node-ffi: они ломают сборку, а эти вызовы
 * достаточно быстрые и не требуют прав сверх тех, что у программы уже есть.
 */
import { execFile, spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
export const IS_WINDOWS = process.platform === 'win32'

/** Выполняет команду, не показывая окно консоли. */
function run(
  file: string,
  args: string[],
  timeout = 15000
): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    execFile(
      file,
      args,
      { windowsHide: true, timeout, maxBuffer: 8 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error && typeof (error as NodeJS.ErrnoException).code === 'number') {
          resolve({ code: (error as NodeJS.ErrnoException & { code: number }).code, stdout, stderr })
          return
        }
        if (error) {
          resolve({ code: 1, stdout, stderr: String(error.message ?? error) })
          return
        }
        resolve({ code: 0, stdout, stderr })
      }
    )
  })
}

/** Запускает PowerShell со скриптом и возвращает текст stdout. */
export async function powershell(script: string, timeout = 20000): Promise<{ code: number; stdout: string; stderr: string }> {
  const tmp = path.join(
    os.tmpdir(),
    `zh-${Date.now()}-${Math.random().toString(36).slice(2)}.ps1`
  )
  try {
    fs.writeFileSync(tmp, `$ErrorActionPreference='SilentlyContinue'\n${script}\n`, 'utf8')
    const result = await run(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', tmp],
      timeout
    )
    return result
  } finally {
    try {
      fs.unlinkSync(tmp)
    } catch {
      /* временный файл не наша забота */
    }
  }
}

/** Есть ли права администратора. */
export function isAdmin(): boolean {
  if (!IS_WINDOWS) return true
  try {
    // net session требует повышения и падает без него
    const { execSync } = require('node:child_process') as typeof import('node:child_process')
    execSync('net session', { stdio: 'ignore', windowsHide: true })
    return true
  } catch {
    return false
  }
}

/** Перезапускает программу с повышением прав через UAC. */
export function relaunchElevated(execPath: string, args: string[] = []): boolean {
  if (!IS_WINDOWS) return false
  try {
    const ps = [
      `$p = Start-Process -FilePath '${execPath.replace(/'/g, "''")}'`,
      `-ArgumentList '${args.join(' ').replace(/'/g, "''")}'`,
      `-Verb RunAs -PassThru`,
      `if ($p) { exit 0 } else { exit 1 }`
    ].join(' ')
    const result = runSyncHidden('powershell.exe', ['-NoProfile', '-Command', ps])
    return result === 0
  } catch {
    return false
  }
}

function runSyncHidden(file: string, args: string[]): number {
  try {
    const { spawnSync } = require('node:child_process') as typeof import('node:child_process')
    const r = spawnSync(file, args, { windowsHide: true, stdio: 'ignore' })
    return r.status ?? 1
  } catch {
    return 1
  }
}

// --------------------------------------------------------------- службы

export type ServiceState = 'RUNNING' | 'STOPPED' | 'START_PENDING' | 'STOP_PENDING' | 'UNKNOWN' | 'NOT_FOUND'

export async function queryService(name: string): Promise<ServiceState> {
  if (!IS_WINDOWS) return 'NOT_FOUND'
  const result = await run('sc', ['query', name])
  if (result.code !== 0) return 'NOT_FOUND'
  const match = /STATE\s*:\s*\d+\s+(\w+)/i.exec(result.stdout)
  if (!match) return 'UNKNOWN'
  return match[1].toUpperCase() as ServiceState
}

export async function removeService(name: string): Promise<boolean> {
  if (!IS_WINDOWS) return false
  // сначала останавливаем, иначе удаление зависнет
  await run('sc', ['stop', name])
  await new Promise((r) => setTimeout(r, 1500))
  const result = await run('sc', ['delete', name])
  return result.code === 0
}

// --------------------------------------------------------------- процессы

/** PID всех дочерних процессов данного PID, включая его самого. */
async function processTree(rootPid: number): Promise<Set<number>> {
  const tree = new Set<number>([rootPid])
  if (!IS_WINDOWS) return tree
  const result = await powershell(
    `Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq ${rootPid} } | Select-Object -ExpandProperty ProcessId`
  )
  for (const line of result.stdout.split(/\r?\n/)) {
    const pid = Number(line.trim())
    if (Number.isFinite(pid) && pid > 0 && !tree.has(pid)) {
      for (const child of await processTree(pid)) tree.add(child)
    }
  }
  return tree
}

/** PID всех запущенных процессов с данным именем образа. */
export async function pidsByName(image: string): Promise<number[]> {
  if (!IS_WINDOWS) return []
  const result = await powershell(
    `Get-Process -Name '${image.replace(/'/g, "''")}' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id`
  )
  return result.stdout
    .split(/\r?\n/)
    .map((line) => Number(line.trim()))
    .filter((pid) => Number.isFinite(pid) && pid > 0)
}

/** Гасит дерево процессов: taskkill /T /F добивает и распакованные копии. */
export async function killTree(pid: number): Promise<void> {
  if (!IS_WINDOWS) return
  for (const child of await processTree(pid)) {
    try {
      process.kill(child)
    } catch {
      /* уже мёртв */
    }
  }
  await run('taskkill', ['/PID', String(pid), '/T', '/F'], 8000)
}

/** Гасит процессы по имени образа, минуя собственные PID. Возвращает убитые. */
export async function killForeignProcesses(image: string, ownPids: Set<number>): Promise<number[]> {
  const pids = await pidsByName(image)
  const killed: number[] = []
  for (const pid of pids) {
    if (ownPids.has(pid)) continue
    const result = await run('taskkill', ['/PID', String(pid), '/T', '/F'], 8000)
    if (result.code === 0) killed.push(pid)
  }
  return killed
}

/** Включает TCP-метки времени — без них часть стратегий не работает. */
export async function enableTcpTimestamps(): Promise<boolean> {
  if (!IS_WINDOWS) return false
  const result = await run('netsh', ['interface', 'tcp', 'set', 'global', 'timestamps=enabled'], 10000)
  return result.code === 0
}

// --------------------------------------------------------------- реестр

const RUN_KEY = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'
const RUN_VALUE = 'ZapretHub'

/** Пишет или убирает запись автозапуска в реестре пользователя. */
export async function setAutostart(enabled: boolean, exePath: string, args: string = '--tray'): Promise<boolean> {
  if (!IS_WINDOWS) return false
  if (!enabled) {
    const result = await run('reg', ['delete', RUN_KEY, '/v', RUN_VALUE, '/f'])
    return result.code === 0
  }
  const value = `"${exePath}"${args ? ` ${args}` : ''}`
  const result = await run('reg', ['add', RUN_KEY, '/v', RUN_VALUE, '/t', 'REG_SZ', '/d', value, '/f'])
  return result.code === 0
}

export async function autostartEnabled(): Promise<boolean> {
  if (!IS_WINDOWS) return false
  const result = await run('reg', ['query', RUN_KEY, '/v', RUN_VALUE])
  return result.code === 0
}

// --------------------------------------------------------------- сеть

export interface PingResult {
  ok: boolean
  ms: number | null
  error: string
}

/** Пинг адреса. Таймаут в миллисекундах. */
export async function ping(host: string, timeoutMs = 2000): Promise<PingResult> {
  if (!IS_WINDOWS) return { ok: false, ms: null, error: 'ping доступен только в Windows' }
  const args = IS_WINDOWS ? ['-n', '1', '-w', String(timeoutMs), host] : ['-c', '1', host]
  const started = Date.now()
  const result = await run('ping', args, timeoutMs + 2000)
  if (result.code !== 0) return { ok: false, ms: null, error: 'нет ответа' }
  const output = `${result.stdout}${result.stderr}`
  const match = /(?:time|время)[=<]\s*(\d+)/i.exec(output)
  const ms = match ? Number(match[1]) : Date.now() - started
  return { ok: true, ms: Number.isFinite(ms) ? ms : null, error: '' }
}

export interface HttpResult {
  /** Ответил ли сайт так, как отвечает работающий сайт. */
  ok: boolean
  /** Код ответа: 200, 301, 403… Ноль — ответа не было. */
  status: number
  /** Код выхода curl: 28, 35… Ноль — запрос дошёл до ответа. */
  code: number
  /** Причина отказа словами. */
  error: string
}

/**
 * Что значит код выхода curl.
 *
 * Без расшифровки «curl: код 28» ничего не говорит: человек видит число и не
 * понимает, сайт заблокирован, сети нет или сертификат протух. А речь как раз
 * о разном: 28 — сайт не ответил вовсе (так ведёт себя закрытый сайт), 35 —
 * рукопожатие TLS разорвали (так ведёт себя закрытие по имени в SNI), 6 — имя
 * вообще не найдено.
 */
const CURL_ERRORS: Record<number, string> = {
  6: 'имя не найдено',
  7: 'соединение не установлено',
  28: 'нет ответа за отведённое время',
  35: 'рукопожатие TLS разорвано',
  52: 'пустой ответ',
  53: 'шифрование не согласовано',
  54: 'соединение сброшено',
  55: 'приём данных сорвался',
  56: 'приём данных сброшен',
  60: 'сертификат не проверяется',
  92: 'протокол HTTP/2 не согласован'
}

/** Пояснение коду выхода curl. */
export function curlError(code: number): string {
  return CURL_ERRORS[code] ?? `curl: код ${code}`
}

/** User-Agent браузера: без него часть сайтов отвечает отказом. */
const USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

/**
 * Проверка сайта по-настоящему.
 *
 * Идёт настоящий GET-запрос с браузерным User-Agent, а не «голова» (-I):
 * многие сайты голову не отдают вовсе или отдают с ошибкой, хотя страница
 * открывается. Ровно это и путало диагностику: сайт живой, а программа
 * считала, что он закрыт, и выбирала по результатам странную стратегию.
 *
 * Различаем три разных случая, потому что они значат разное:
 *   • ответ пришёл (любой код) — сайт доступен, дальше дело сервера;
 *   • запрос сорвался (28, 35, 54…) — сайт закрыт;
 *   • 4xx/5xx — сайт ответил, но не тем, что мы просили: это не блокировка.
 */
export async function httpCheck(url: string, timeoutMs = 6000): Promise<HttpResult> {
  const seconds = String(Math.max(2, Math.ceil(timeoutMs / 1000)))
  const result = await run(
    'curl.exe',
    [
      '-s',
      '-L',
      '-A',
      USER_AGENT,
      '--connect-timeout',
      seconds,
      '-m',
      seconds,
      '-o',
      'NUL',
      '-w',
      '%{http_code}',
      url
    ],
    timeoutMs + 3000
  )
  const status = Number(result.stdout.trim().split(/\s+/).pop())
  const code = result.code === 0 ? 0 : result.code

  if (code !== 0) {
    return { ok: false, status: Number.isFinite(status) && status > 0 ? status : 0, code, error: curlError(code) }
  }
  if (!Number.isFinite(status) || status === 0) {
    return { ok: false, status: 0, code: 0, error: 'ответа нет' }
  }
  if (status >= 400) {
    return { ok: false, status, code: 0, error: `HTTP ${status}` }
  }
  return { ok: true, status, code: 0, error: '' }
}

/** Запускает дочерний процесс, не создавая окна консоли. */
export function spawnDetached(
  command: string,
  args: string[],
  options: { cwd?: string; env?: NodeJS.ProcessEnv } = {}
) {
  return spawn(command, args, {
    cwd: options.cwd,
    env: options.env ?? process.env,
    windowsHide: true,
    detached: process.platform === 'win32',
    stdio: ['ignore', 'pipe', 'pipe']
  })
}

// ---------------------------------------------------------------- дозорный

/** Строковый список для PowerShell: @('a','b'). */
function psList(items: string[]): string {
  return `@(${items.map((item) => `'${item.replace(/'/g, "''")}'`).join(',')})`
}

/**
 * Текст дозорного — крошечного процесса, который дожидается смерти программы
 * и гасит всё, что она за собой оставила.
 *
 * Зачем: Windows не убивает дочерние процессы вслед за родителем. Компоненты
 * запущены отдельно (detached), поэтому «снять задачу Zapret Hub» в диспетчере
 * задач, падение программы или обрыв питания оставляли winws.exe и
 * TgWsProxy_windows.exe работать уже без хозяина: обход оставался включённым
 * без всякого управления, а файлы компонентов держались занятыми — из-за чего
 * программа потом не обновлялась и не удалялась.
 *
 * Дозорный живёт, пока живы и программа, и её компоненты. Программа исчезла —
 * он гасит компоненты (сначала по номерам, вместе с деревом, потом по имени
 * образа — вдруг компонент успел породить копию себя) и уходит сам. Компоненты
 * исчезли раньше — уходит, не дожидаясь программы: иначе дозорные копились бы
 * при каждом останове обхода.
 *
 * Пишем на PowerShell: это есть в любой Windows 10+, и не нужен ни нативный
 * модуль (он ломает сборку), ни объект «задание», который в Node не достать.
 */
export function guardianScript(hubPid: number, victims: number[], images: string[]): string {
  // Тело цикла: ждём, пока живы и программа, и компоненты.
  const loop = [
    // программа исчезла — гасим
    'if(-not (Get-Process -Id $hub -ErrorAction SilentlyContinue)){break}',
    // компоненты кончились раньше программы — дозорный больше не нужен
    '$alive=$false',
    'foreach($pid in $victims){if(Get-Process -Id $pid -ErrorAction SilentlyContinue){$alive=$true}}',
    'if(-not $alive){exit}',
    'Start-Sleep -Milliseconds 800'
  ].join(';')

  // PowerShell разделяет команды точкой с запятой, а не переводом строки:
  // строка уезжает одной командой, и слипшиеся команды он не поймёт.
  const statements = [
    `$hub=${hubPid}`,
    `$victims=${psList(victims.map(String))}`,
    `$images=${psList(images)}`,
    `while(1){${loop}}`,
    // гасим по номерам, вместе с деревом: это ровно те процессы, что запустила программа
    'foreach($pid in $victims){taskkill /PID $pid /T /F | Out-Null}',
    // и добиваем по имени образа: TgWsProxy распаковывает копию себя
    'foreach($image in $images){taskkill /IM "$image.exe" /T /F | Out-Null}',
    'exit'
  ]
  return statements.join(';')
}

/**
 * Запускает дозорного. Возвращает его процесс, чтобы программа могла снять
 * дозорного сама — например, при собственном перезапуске, когда гасить обходы
 * как раз не надо.
 */
export function spawnGuardian(
  hubPid: number,
  victims: number[],
  images: string[] = []
): ChildProcess | null {
  if (!IS_WINDOWS) return null
  const alive = victims.filter((pid) => Number.isFinite(pid) && pid > 0)
  if (alive.length === 0) return null
  try {
    return spawn(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-WindowStyle',
        'Hidden',
        '-Command',
        guardianScript(hubPid, alive, images)
      ],
      { windowsHide: true, detached: true, stdio: 'ignore' }
    )
  } catch {
    // не смогли поставить дозорного — работаем дальше: это страховка, а не
    // обязательное условие запуска обхода
    return null
  }
}
