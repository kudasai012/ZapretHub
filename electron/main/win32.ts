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

/**
 * Выполняет команду, не показывая окно консоли.
 *
 * Наружу — для модулей вроде sysdiag, которым нужны свои вызовы sc и netsh.
 * Здесь они и остаются: единственное место, где программа общается с системой.
 */
export function run(
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

/**
 * Состояние службы.
 *
 * Спрашиваем Get-Service, а не разбираем вывод `sc query`: sc печатает состояние
 * на языке системы, и на русской Windows строка просто не узнавалась — проверка
 * показывала сырое «UNKNOWN» вместо понятного ответа.
 */
export async function queryService(name: string): Promise<ServiceState> {
  if (!IS_WINDOWS) return 'NOT_FOUND'
  const safe = name.replace(/'/g, "''")
  const ps =
    `$s = Get-Service -Name '${safe}' -ErrorAction SilentlyContinue; ` +
    "if ($null -eq $s) { 'NOT_FOUND' } else { $s.Status.ToString().ToUpperInvariant() }"
  const result = await powershell(ps, 15000)
  const lines = result.stdout.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const state = (lines[lines.length - 1] ?? '').toUpperCase()
  if (state === 'NOT_FOUND') return 'NOT_FOUND'
  if (state === '') {
    // PowerShell не ответил — пробуем старый путь, чтобы не врать про «нет службы»
    const sc = await run('sc', ['query', name])
    if (sc.code !== 0) return 'NOT_FOUND'
    const match = /STATE\s*:\s*\d+\s+(\w+)/i.exec(sc.stdout)
    return match ? (match[1].toUpperCase() as ServiceState) : 'UNKNOWN'
  }
  return state as ServiceState
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
const TCP_PARAM_KEY = 'HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters'

/**
 * Значение Tcp1323Opts: бит 0 — масштабирование окна, бит 1 — метки времени.
 * null — значения в реестре нет, действует встроенный по умолчанию.
 *
 * Читаем реестр, а не вывод `netsh interface tcp show global`: netsh печатает
 * названия параметров на языке системы, поэтому на русской Windows подстрока
 * «timestamps» в выводе не находилась и проверка вечно показывала «выключено» —
 * даже сразу после того, как метки включили.
 */
export async function tcpTimestampsOpt(): Promise<number | null> {
  if (!IS_WINDOWS) return null
  const ps =
    "$v = (Get-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters' " +
    "-Name Tcp1323Opts -ErrorAction SilentlyContinue).Tcp1323Opts; " +
    "if ($null -eq $v) { '' } else { [int]$v }"
  const result = await powershell(ps, 15000)
  const lines = result.stdout.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const value = Number.parseInt(lines[lines.length - 1] ?? '', 10)
  return Number.isFinite(value) ? value : null
}

/** Включены ли метки времени: бит 1 в Tcp1323Opts. */
export function timestampsOn(opt: number | null): boolean {
  return opt !== null && (opt & 2) !== 0
}

/**
 * Включает метки времени, не выключая по пути масштабирование окна.
 *
 * Один netsh сбрасывает Tcp1323Opts целиком в 2: метки появляются, а
 * масштабирование окна гаснет. Поэтому сначала netsh — чтобы подействовало на
 * уже работающие соединения, — потом реестр, где выставлен только нужный бит.
 */
export async function enableTcpTimestamps(): Promise<boolean> {
  if (!IS_WINDOWS) return false
  await run('netsh', ['interface', 'tcp', 'set', 'global', 'timestamps=enabled'], 10000)
  const current = await tcpTimestampsOpt()
  const next = (current ?? 3) | 2
  const result = await run(
    'reg',
    ['add', TCP_PARAM_KEY, '/v', 'Tcp1323Opts', '/t', 'REG_DWORD', '/d', String(next), '/f'],
    10000
  )
  return result.code === 0
}

// --------------------------------------------------------------- реестр

const RUN_KEY = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'
const RUN_VALUE = 'ZapretHub'

/** Пишет или убирает запись автозапуска в реестре пользователя. */
/**
 * Ключ, с которым Windows поднимает программу при входе в систему.
 *
 * Его пишет в реестр автозапуск, и по нему программа понимает, что её
 * запустил вход в Windows, а не человек. Разница важна: при входе в систему
 * окно не показывается вовсе — программа поднимается в трей и молча делает
 * свою работу. Человек же, запустивший программу руками, видит окно, если не
 * включил «запускать свёрнутым». Это две разные настройки, и путать их нельзя.
 *
 * Константа одна на оба места — запись в реестр и проверку при старте:
 * разойдись они, автозапуск снова начал бы раскрывать окно на весь экран.
 */
export const LOGIN_ARG = '--tray'

/** Программу поднял вход в Windows, а не человек. */
export function startedAtLogin(): boolean {
  return process.argv.includes(LOGIN_ARG)
}

export async function setAutostart(
  enabled: boolean,
  exePath: string,
  args: string = LOGIN_ARG
): Promise<boolean> {
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
  const verdict = httpVerdict(code, status)
  return {
    ok: verdict.ok,
    status: Number.isFinite(status) && status > 0 ? status : 0,
    code,
    error: verdict.error
  }
}

/**
 * Открылся ли сайт по итогу запроса.
 *
 * Любой код ответа — сайт открылся. Даже 404: он значит, что рукопожатие TLS
  // и сам запрос прошли, провайдер в канал не влез, а «не тем ответил» — уже
  // забота сервера. Ровно так считает и проверка самого пакета (utils/test
  // zapret.ps1): там «HTTP:OK» — это успешный запуск curl, а не код 200.
  //
  // Прежняя правила «статус >= 400 — сайт закрыт» объявляла битыми живые
  // страницы: корни cdn.discordapp.com, i.ytimg.com, redirector.googlevideo.com
  // и www.gstatic.com отдают 403/404 всегда, и стратегия получала 65 % там, где
  // проверка пакета показывала 100 % и все OK. Отсюда и расхождение, и «нерабочие»
  // стратегии, которые на самом деле работали.
  //
  // Отдельной функцией — чтобы правило можно было проверить тестом: curl.exe в
  // песочнице нет, а поведение «404 значит ок» проверять обязательно.
 */
export function httpVerdict(exitCode: number, status: number): { ok: boolean; error: string } {
  // curl не дотянулся: таймаут (28), обрыв на сертификате (35), сброс (54).
  if (exitCode !== 0) return { ok: false, error: curlError(exitCode) }
  if (!Number.isFinite(status) || status <= 0) return { ok: false, error: 'ответа нет' }
  return { ok: true, error: '' }
}

/**
 * PID всех процессов, у которых в пути к exe есть эта подстрока.
 *
 * Зачем: TgWsProxy в портативном режиме распаковывает копию себя, и процесс,
 * который остаётся висеть в трее, называется не так, как файл, который мы
 * запустили. Гасить по имени запущенного файла бесполезно — надо по пути.
 */
export async function pidsByPathNeedle(needle: string): Promise<number[]> {
  if (!IS_WINDOWS || !needle) return []
  const escaped = needle.replace(/'/g, "''")
  const result = await powershell(
    `Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*${escaped}*' } | Select-Object -ExpandProperty Id`
  )
  return readPids(result.stdout)
}

/** PID всех процессов, которые слушают порт. */
export async function pidsByPort(port: number): Promise<number[]> {
  if (!IS_WINDOWS || !Number.isFinite(port) || port <= 0) return []
  const result = await run('netstat', ['-ano'], 20000)
  return parseNetstatPids(result.stdout, port)
}

/** Достаёт числа из вывода команды, по одному PID на строку. */
export function readPids(text: string): number[] {
  return text
    .split(/\r?\n/)
    .map((line) => Number(line.trim()))
    .filter((pid) => Number.isFinite(pid) && pid > 0)
}

/**
 * Разбирает вывод `netstat -ano` и отдаёт PID, слушающие порт.
 *
 * Строка выглядит так:
 *   TCP    127.0.0.1:1443    0.0.0.0:0    LISTENING    4812
 * Смотрим только LISTENING: иначе порт на той стороне чужого соединения тоже
 * попал бы в ответ, и программа гасила бы не те процессы.
 *
 * Отдельной функцией — чтобы правило разбора проверялось тестом: netstat в
 * песочнице нет, а ошибка здесь значит «гасим не тех».
 */
export function parseNetstatPids(text: string, port: number): number[] {
  const pids = new Set<number>()
  const marker = `:${port}`
  const NL = String.fromCharCode(10)
  for (const line of text.split(NL)) {
    // Столбцы netstat: протокол, локальный адрес, внешний адрес, состояние, PID.
    const columns = line.trim().split(/ +/).filter(Boolean)
    if (columns.length < 5) continue
    if (!/LISTENING/i.test(columns[3])) continue
    // Слушаем мы свой локальный адрес: порт на той стороне чужого соединения
    // не считаем — иначе программа гасила бы не те процессы.
    if (!columns[1].endsWith(marker)) continue
    const pid = Number(columns[columns.length - 1])
    if (Number.isFinite(pid) && pid > 0) pids.add(pid)
  }
  return [...pids]
}

/**
 * Запускает процесс «отвязанным»: переживёт закрытие программы, если она
 * перестанет за ним следить.
 *
 * Нужен для компонентов: winws.exe и TgWsProxy должны продолжать работать,
 * пока программа перезапускается.
 */
export function spawnDetached(
  command: string,
  args: string[],
  options: { cwd?: string; env?: NodeJS.ProcessEnv } = {}
): ChildProcess {
  return spawn(command, args, {
    cwd: options.cwd,
    env: options.env ?? process.env,
    windowsHide: true,
    detached: process.platform === 'win32',
    stdio: ['ignore', 'pipe', 'pipe']
  })
}

/** Список строк в виде PowerShell-массива: @('a','b'). */
function psList(items: string[]): string {
  return `@(${items.map((item) => `'${item.replace(/'/g, "''")}'`).join(',')})`
}

// ------------------------------------------------------ задание Windows (job)

/**
 * Версия сборки-помощника.
 *
 * Меняем, когда меняется исходник: имя файла — единственное, чем отличается
 * свежая сборка от устаревшей, оставшейся в temp от прошлой версии программы.
 */
export const JOB_HELPER_VERSION = 'v1'

/**
 * Исходник сборки-помощника на C#: из неё дозорный достаёт задание Windows.
 *
 * Задание (job object) — то самое средство, которого не хватало. Дерево
 * процессов здесь не помощник: TgWsProxy в портативном режиме распаковывает
 * копию себя и выходит, копия теряет родителя и покидает наше дерево — снятие
 * задачи её не задевает. А участник задания остаётся участником, кто бы ни был
 * его родителем: задание наследуется детьми и переживает выход родителя.
 *
 * С меткой KILL_ON_JOB_CLOSE система сама гасит всех участников, когда
 * закрывается последний дескриптор задания — то есть в ту же секунду, когда
 * гаснет держащий его дозорный. Ни одна наша строчка при этом не срабатывает:
 * гасит ядро, и гасит безотказно.
 *
 * Дозорный — дитя программы, поэтому «Завершить задачу» убирает и его. Это и
 * есть спусковой крючок: дескриптор закрылся — задание рассыпалось — копия
 * TgWsProxy умерла вместе с ним.
 */
export const JOB_HELPER_SOURCE = `using System;
using System.Runtime.InteropServices;

public class HubJob
{
    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint size);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inherit, int pid);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    private const int JobObjectExtendedLimitInformation = 9;
    private const uint KillOnJobClose = 0x2000;
    private const uint SetQuota = 0x0100;
    private const uint Terminate = 0x0001;
    private const uint QueryLimitedInformation = 0x1000;

    public static IntPtr Create()
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) return IntPtr.Zero;
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = KillOnJobClose;
        uint size = (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref info, size))
        {
            CloseHandle(job);
            return IntPtr.Zero;
        }
        return job;
    }

    public static bool Assign(IntPtr job, int pid)
    {
        IntPtr process = OpenProcess(SetQuota | Terminate | QueryLimitedInformation, false, pid);
        if (process == IntPtr.Zero) return false;
        try { return AssignProcessToJobObject(job, process); }
        finally { CloseHandle(process); }
    }

    public static bool Release(IntPtr job)
    {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = 0;
        uint size = (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        return SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref info, size);
    }
}
`

/** Путь к исходнику сборки-помощника. */
export function jobHelperSourcePath(): string {
  return path.join(os.tmpdir(), `ZapretHub.HubJob.${JOB_HELPER_VERSION}.cs`)
}

/** Путь к скомпилированной сборке-помощнику. */
export function jobHelperAssemblyPath(): string {
  return path.join(os.tmpdir(), `ZapretHub.HubJob.${JOB_HELPER_VERSION}.dll`)
}

/** Кладёт исходник сборки-помощника в temp. Пустая строка — не записалось. */
export function writeJobHelper(): string {
  const target = jobHelperSourcePath()
  try {
    fs.writeFileSync(target, JOB_HELPER_SOURCE, 'utf8')
    return target
  } catch {
    return ''
  }
}

/**
 * Компилирует сборку-помощника заранее, не дожидаясь первого компонента.
 *
 * Компиляция занимает секунду-две. Если делать её в момент запуска компонента,
 * всё это время распакованная копия TgWsProxy живёт без задания: снятая задача
 * в эту секунду — и прокси опять висит в трее. Поэтому готовим сборку сразу
 * после старта программы, чтобы дозорный поднимался за доли секунды.
 */
export function warmUpJobHelper(): void {
  if (!IS_WINDOWS) return
  const source = writeJobHelper()
  if (!source) return
  const assembly = jobHelperAssemblyPath()
  let ready = false
  try {
    ready = fs.existsSync(assembly)
  } catch {
    /* проверить не вышло — всё равно попробуем */
  }
  if (ready) return
  const script = [
    "$ErrorActionPreference='SilentlyContinue'",
    `if(-not (Test-Path -LiteralPath '${assembly}')){`,
    `Add-Type -LiteralPath '${source}' -OutputAssembly '${assembly}'`,
    '}'
  ].join('\n')
  try {
    spawn(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-Command', script],
      { windowsHide: true, detached: true, stdio: 'ignore' }
    ).unref()
  } catch {
    /* нет PowerShell — дозорный соберёт сборку сам, просто не сразу */
  }
}

/** Путь к метке «компонент отпущен, гасить не надо». */
export function releaseFlagPath(key: string): string {
  return path.join(os.tmpdir(), `ZapretHub.Release.${key}.${process.pid}.flag`)
}

/**
 * Кладёт метку «этот компонент больше не под присмотром».
 *
 * Дозорный читает её в ту секунду, когда программа исчезла: если метка есть,
 * он снимает с задания гасящую метку и выходит, оставляя компонент работать.
 * Без неё перезапуск программы гасил бы обходы: дозорный принял бы исчезновение
 * программы за аварию.
 */
export function writeReleaseFlag(key: string): string {
  const target = releaseFlagPath(key)
  try {
    fs.writeFileSync(target, '1', 'utf8')
    return target
  } catch {
    return ''
  }
}

/**
 * Убирает метку «компонент отпущен».
 *
 * Метка лежит в temp и доживает до конца сеанса. Если её не стереть, новый
 * дозорный найдёт чужую метку и откажется гасить компонент: снятая задача
 * снова оставит прокси висеть. Поэтому каждый новый дозорный начинает с
 * чистого листа.
 */
export function clearReleaseFlag(key: string): void {
  try {
    fs.rmSync(releaseFlagPath(key), { force: true })
  } catch {
    /* метки и не было */
  }
}

/** Убирает из temp старые сценарии дозорных и старые метки. */
function cleanupTempFiles(keep: string[]): void {
  try {
    for (const name of fs.readdirSync(os.tmpdir())) {
      if (!/^ZapretHub\.(Guardian\..*\.ps1|Release\..*\.flag)$/.test(name)) continue
      const full = path.join(os.tmpdir(), name)
      if (keep.includes(full)) continue
      try {
        if (Date.now() - fs.statSync(full).mtimeMs > 6 * 3600 * 1000) fs.unlinkSync(full)
      } catch {
        /* файл занят или уже убран */
      }
    }
  } catch {
    /* temp недоступен — не до уборки */
  }
}

export interface GuardianOptions {
  /** Ключ компонента: по нему имя сценария в temp. */
  key: string
  /** PID программы: пока он жив, компонент работает. */
  hubPid: number
  /** PID, с которых компонент запускали. */
  victims: number[]
  /** Имена образов: TgWsProxy_windows, winws — без .exe. */
  images?: string[]
  /** Подстроки в пути: распакованная копия называется иначе, путь тот же. */
  needles?: string[]
  /** Порты, которые компонент слушает. */
  ports?: number[]
  /** Гасить компонент, когда программа исчезла. */
  killOnExit: boolean
  /** Куда писать разбор полётов. */
  logPath?: string
  /** Файл настроек: дозорный читает настройку в момент смерти программы. */
  configPath?: string
}

/** Аргументы, с которыми запускаем PowerShell по файлу, а не по командной строке. */
const PS_FILE_ARGS = [
  '-NoProfile',
  '-NonInteractive',
  '-WindowStyle',
  'Hidden',
  '-ExecutionPolicy',
  'Bypass',
  '-File'
]

/**
 * Сценарий дозорного на PowerShell.
 *
 * Дозорный делает две вещи. Первая — держит задание Windows, в которое принял
 * компонент: пока дескриптор задания жив, компонент работает, а как только
 * дескриптор закроется, система сама погасит всех участников задания. Закрывает
 * его всё, что угодно: выход самого дозорного по любой причине, а чаще всего —
 * снятая задача в диспетчере, которая гасит программу вместе с детьми, и
 * дозорного в том числе.
 *
 * Вторая — подбирает в задание всё, что появилось после запуска. TgWsProxy
 * распаковывает копию себя через секунду после старта, и копию надо принять:
 * по номеру она уже не наш (запущенный нами процесс успел выйти), зато её
 * видно по имени образа, по подстроке в пути и по порту.
 *
 * И сверх того — старое добивание taskkill: если программу сняли так, что
 * дозорный выжил, он всё равно погасит компонент сам.
 */
export function guardianScript(options: GuardianOptions): string {
  const images = (options.images ?? []).filter(Boolean)
  const needles = (options.needles ?? []).filter(Boolean)
  const ports = (options.ports ?? []).filter((port) => Number.isFinite(port) && port > 0)
  const log = options.logPath ?? ''
  const cfg = options.configPath ?? ''
  const source = jobHelperSourcePath()
  const assembly = jobHelperAssemblyPath()
  const flag = releaseFlagPath(options.key)

  return [
    "$ErrorActionPreference='SilentlyContinue'",
    `$log='${log}'`,
    `$cfg='${cfg}'`,
    `$cs='${source}'`,
    `$dll='${assembly}'`,
    `$flag='${flag}'`,
    `$self='${process.execPath}'`,
    `$hub=${options.hubPid}`,
    `$victims=${psList(options.victims.map(String))}`,
    `$images=${psList(images)}`,
    `$needles=${psList(needles)}`,
    `$ports=${psList(ports.map(String))}`,
    `$wantKill=${options.killOnExit ? 1 : 0}`,
    // Запись в журнал. Перед первым запуском подчищаем разросшийся файл: он
    // копится от сессии к сессии и без этого распухает до мегабайт.
    'function glog($m){',
    '  try{',
    "    if((Get-Item -LiteralPath $log -ErrorAction SilentlyContinue).Length -gt 524288){ Set-Content -LiteralPath $log -Value '' -Encoding UTF8 }",
    "    Add-Content -LiteralPath $log -Value ((Get-Date -Format 'HH:mm:ss') + ' ' + $m) -Encoding UTF8",
    '  }catch{}',
    '}',
    // Кто слушает порт. netstat, а не Get-NetTCPConnection: тот перебирает
    // все соединения в системе и на загруженной машине думает десятки
    // секунд. Дозорный, застрявший в нём, не замечал, что программы уже нет,
    // и ничего не гасил — ровно это и выглядело как «дозорный не работает».
    // Строка выглядит так:
    //   TCP    127.0.0.1:1443    0.0.0.0:0    LISTENING    4812
    'function pidsOnPort($pt){',
    '  $out=@()',
    '  foreach($line in (netstat -ano -p tcp)){',
    "    if($line -notmatch 'LISTENING'){ continue }",
    "    $cols = ($line.Trim() -split '\\s+')",
    '    if($cols.Count -lt 5){ continue }',
    "    if(-not $cols[1].EndsWith(':' + $pt)){ continue }",
    '    $p = 0',
    "    if([int]::TryParse($cols[4], [ref]$p) -and $p -gt 0){ $out += $p }",
    '  }',
    '  return $out',
    '}',
    // Все, кто похож на наш компонент, четырьмя способами. Ни себя, ни саму
    // программу, ни её окна в это число не берём никогда: задание закрывается
    // гашением всех участников, и чужой процесс внутри — это уже поломка.
    // Окна программы — тот же самый ZapretHub.exe, просто с другими номерами,
    // поэтому мало убрать один номер программы: убираем весь исполняемый файл.
    'function candidates(){',
    '  $all=@()',
    '  $all+=$victims',
    '  foreach($n in $images){ $all+=(Get-Process -Name $n -ErrorAction SilentlyContinue | Where-Object { $_.Path -ne $self } | Select-Object -ExpandProperty Id) }',
    '  foreach($nd in $needles){ $all+=(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$nd*" -and $_.Path -ne $self } | Select-Object -ExpandProperty Id) }',
    '  foreach($pt in $ports){ $all+=(pidsOnPort $pt) }',
    // Мёртвые номера в ответ не берём. Иначе «гасить больше нечего» не
    // наступает никогда: номер запущенного нами процесса известен всегда,
    // даже когда сам процесс давно убит, и добивание крутилось бы до конца
    // отведённого срока, вместо того чтобы закончить после первого прохода.
    '  return ($all | Where-Object { $_ -gt 0 -and $_ -ne $hub -and $_ -ne $PID } | Sort-Object -Unique | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })',
    '}',
    // Гасим тем же набором способов, что и ищем: по номеру, по имени образа,
    // по подстроке в пути и по порту. Распакованная копия называется не так,
    // как файл, который мы запускали, поэтому одного имени мало.
    'function killAll(){',
    '  foreach($p in (candidates)){ taskkill /PID $p /T /F | Out-Null }',
    '  foreach($im in $images){',
    '    taskkill /IM "$im.exe" /T /F | Out-Null',
    '    Get-Process -Name $im -ErrorAction SilentlyContinue | Where-Object { $_.Path -ne $self } | ForEach-Object { taskkill /PID $_.Id /T /F | Out-Null }',
    '  }',
    '  foreach($nd in $needles){ Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$nd*" -and $_.Path -ne $self } | ForEach-Object { taskkill /PID $_.Id /T /F | Out-Null } }',
    '  foreach($pt in $ports){ foreach($p in (pidsOnPort $pt)){ taskkill /PID $p /T /F | Out-Null } }',
    '}',
    // Задание. Сборку берём готовой (её скомпилировали при старте программы),
    // а нет — собираем сами прямо сейчас.
    '$job=0',
    'try{',
    "  if(-not (Test-Path -LiteralPath $dll)){ Add-Type -LiteralPath $cs -OutputAssembly $dll -ErrorAction SilentlyContinue }",
    "  if(Test-Path -LiteralPath $dll){ Add-Type -LiteralPath $dll -ErrorAction Stop }",
    "  else { Add-Type -LiteralPath $cs -ErrorAction Stop }",
    '  $job=[HubJob]::Create()',
    '}catch{',
    "  glog ('нет задания: ' + $_.Exception.Message)",
    '  $job=0',
    '}',
    "glog ('дозорный встал: задание=' + $job + ' номера=' + ($victims -join ',') + ' образы=' + ($images -join ','))",
    '$adopted=@{}',
    // Сторожим программу. Проверяем её каждые 300 мс, а подбор компонентов
    // делаем по своему расписанию: он перебирает процессы и потому дороже.
    // Часто — первые пятнадцать проходов, пока TgWsProxy распаковывает копию;
    // потом изредка, чтобы не жечь процессор зря.
    '$lastAdopt=0',
    '$every=1000',
    '$pass=0',
    'while(1){',
    '  if(-not (Get-Process -Id $hub -ErrorAction SilentlyContinue)){ break }',
    '  $now=[Environment]::TickCount',
    '  if($now - $lastAdopt -ge $every){',
    '    $t0=[Environment]::TickCount',
    '    $pass++',
    '    if($job -ne 0){',
    '      foreach($p in (candidates)){',
    '        if($adopted[$p]){ continue }',
    "        if([HubJob]::Assign($job,[int]$p)){ $adopted[$p]=1; glog ('принял ' + $p) }",
    '      }',
    '    }',
    '    $spent=[Environment]::TickCount-$t0',
    "    if($pass -le 15 -or $spent -gt 800){ glog ('подбор ' + $pass + ': ' + $spent + ' мс') }",
    '    $lastAdopt=[Environment]::TickCount',
    '    if($pass -ge 15){ $every=20000 }',
    '  }',
    '  Start-Sleep -Milliseconds 300',
    '}',
    "glog 'программы нет'",
    // Гасить или отпустить. Решаем по живьём прочитанным настройкам: человек
    // мог переключить их после запуска компонента. Метка «отпущен» важнее
    // настроек: её кладут при перезапуске программы, когда обход должен
    // выжить при любом значении настройки.
    '$kill=$wantKill',
    'try{',
    '  if(Test-Path -LiteralPath $cfg){',
    '    $j=Get-Content -LiteralPath $cfg -Raw | ConvertFrom-Json',
    '    if($j.general.stopComponentsOnQuit -eq $false){ $kill=0 } else { $kill=1 }',
    '  }',
    '}catch{}',
    "if(Test-Path -LiteralPath $flag){ $kill=0; glog 'компонент отпущен' }",
    'if($kill -eq 1){',
    // Гасим несколькими проходами: процесс может умирать не сразу, а у
    // TgWsProxy есть сторож, который поднимает его заново.
    '  $deadline=[Environment]::TickCount+12000',
    '  $round=0',
    '  while([Environment]::TickCount -lt $deadline){',
    '    $round++',
    '    killAll',
    '    if(@(candidates).Count -eq 0){ break }',
    '    Start-Sleep -Milliseconds 600',
    '  }',
    "  glog ('добил сам, проходов: ' + $round)",
    '}else{',
    "  if($job -ne 0){ [HubJob]::Release($job) | Out-Null; glog 'задание снято, компонент живёт' }",
    '}',
    'exit'
  ].join('\n')
}

/**
 * Кладёт сценарий дозорного в temp и отдаёт путь к нему.
 *
 * Файлом, а не командной строкой: сценарий длинный, а в командной строке и
 * длина ограничена, и кавычки приходится экранировать дважды — на каждом таком
 * экранировании дозорный ломался. Пишем с BOM: PowerShell 5.1 без метки читает
 * файл в системной кодировке, и кириллица в журнале превращается в кракозябры.
 */
export function writeGuardianScript(key: string, script: string): string {
  const file = path.join(os.tmpdir(), `ZapretHub.Guardian.${key}.${process.pid}.ps1`)
  try {
    fs.writeFileSync(file, `﻿${script}`, 'utf8')
    cleanupTempFiles([file])
    return file
  } catch {
    return ''
  }
}

/**
 * Поднимает дозорного: отдельный PowerShell, который держит задание Windows с
 * компонентом внутри и гасит компонент, если программу убьют вслепую.
 */
export function spawnGuardian(options: GuardianOptions): ChildProcess | null {
  if (!IS_WINDOWS) return null
  const victims = options.victims.filter((pid) => Number.isFinite(pid) && pid > 0)
  if (victims.length === 0) return null
  const script = guardianScript({ ...options, victims })
  const file = writeGuardianScript(options.key, script)
  if (!file) return null
  try {
    return spawn('powershell.exe', [...PS_FILE_ARGS, file], {
      windowsHide: true,
      detached: true,
      stdio: 'ignore'
    })
  } catch {
    return null
  }
}
