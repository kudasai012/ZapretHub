/**
 * Обновление компонентов и самой программы.
 *
 * Оба источника — GitHub Releases. Программа сама себя не перезаписывает
 * (exe занят, пока программа работает), поэтому для обновления себя она
 * скачивает установщик и запускает его, остановив компоненты: иначе файлы
 * компонентов заняты winws.exe.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { app, shell } from 'electron'
import type { AppUpdateInfo, ComponentKey, UpdateInfo, UpdateProgress } from '@shared/contract'
import { BACKUPS_DIR } from './paths'
import { configStore, dueForCheck, tmpDir } from './config'
import { emit } from './ipc'
import { logger } from './logger'
import { ZapretComponent } from './zapret'
import { TgWsComponent, EXE_NAME } from './tgws'

const GITHUB_API = 'https://api.github.com'

export const REPOS: Record<ComponentKey, string> = {
  zapret: 'Flowseal/zapret-discord-youtube',
  tgws: 'Flowseal/tg-ws-proxy'
}

export const APP_REPO = 'kudasai012/ZapretHub'

interface GitHubAsset {
  name: string
  browser_download_url: string
  size: number
}

interface GitHubRelease {
  tag_name: string
  html_url: string
  body: string
  published_at: string
  assets: GitHubAsset[]
}

/** Сравнение версий: «1.10.2» больше «1.9.3». */
export function compareVersions(a: string, b: string): number {
  const pa = a.replace(/^v/, '').split(/[.\-+]/).map((part) => (/^\d+$/.test(part) ? Number(part) : part))
  const pb = b.replace(/^v/, '').split(/[.\-+]/).map((part) => (/^\d+$/.test(part) ? Number(part) : part))
  const len = Math.max(pa.length, pb.length)
  for (let i = 0; i < len; i += 1) {
    const x = pa[i] ?? 0
    const y = pb[i] ?? 0
    if (typeof x === 'number' && typeof y === 'number') {
      if (x !== y) return x - y
      continue
    }
    const sx = String(x)
    const sy = String(y)
    if (sx !== sy) return sx < sy ? -1 : 1
  }
  return 0
}

/** Запрос к GitHub API. */
async function github<T>(endpoint: string): Promise<T> {
  const url = `${GITHUB_API}${endpoint}`
  const args = [
    '-s', '-L', '-f', '-m', '25',
    '-H', 'Accept: application/vnd.github+json',
    '-H', 'User-Agent: ZapretHub',
    url
  ]

  const { execFile } = require('node:child_process') as typeof import('node:child_process')
  const { promisify } = require('node:util') as typeof import('node:util')
  const run = promisify(execFile)
  const { stdout } = await run('curl.exe', args, { windowsHide: true, maxBuffer: 16 * 1024 * 1024 })
  return JSON.parse(stdout) as T
}

/** Файлы релиза — пустой список, если их нет. */
function assets(release: GitHubRelease | null): GitHubAsset[] {
  return release && Array.isArray(release.assets) ? release.assets : []
}

async function latestRelease(repo: string): Promise<GitHubRelease | null> {
  try {
    const release = await github<GitHubRelease>(`/repos/${repo}/releases/latest`)
    // без tag_name и без файлов это не релиз, а ответ об ошибке — например,
    // 404, если репозиторий переехал. Раньше такой ответ доходил до
    // release.assets.find(...) и ронял обновление с «Cannot read properties
    // of undefined».
    if (!release?.tag_name || !Array.isArray(release.assets)) return null
    return release
  } catch (error) {
    logger.write(`[updater] не удалось получить релиз ${repo}: ${String(error)}`)
    return null
  }
}

/** Ищет обновления компонентов. */
export async function checkComponents(
  zapret: ZapretComponent,
  tgws: TgWsComponent,
  force = false
): Promise<UpdateInfo[]> {
  if (!force && !dueForCheck(configStore.get().updates.lastCheck)) return []
  if (!force && !configStore.get().updates.autoCheck) return []

  configStore.get().updates.lastCheck = Date.now() / 1000
  configStore.save()

  const found: UpdateInfo[] = []
  const current: Record<ComponentKey, string> = {
    zapret: zapret.version() ?? '0',
    tgws: tgws.version() ?? '0'
  }

  for (const key of ['zapret', 'tgws'] as ComponentKey[]) {
    const release = await latestRelease(REPOS[key])
    if (!release?.tag_name) continue
    const latest = release.tag_name.replace(/^v/, '')
    if (compareVersions(latest, current[key]) > 0) {
      found.push({
        key,
        current: current[key],
        latest,
        url: release.html_url,
        notes: (release.body ?? '').slice(0, 4000)
      })
    }
  }
  return found
}

/** Ищет обновление самой программы. */
export async function checkApp(force = false): Promise<AppUpdateInfo | null> {
  if (!force && !configStore.get().updates.autoCheck) return null
  const release = await latestRelease(APP_REPO)
  if (!release?.tag_name) return null
  const latest = release.tag_name.replace(/^v/, '')
  const current = app.getVersion()
  if (compareVersions(latest, current) <= 0) return null
  return {
    current,
    latest,
    url: release.html_url,
    notes: (release.body ?? '').slice(0, 4000),
    publishedAt: release.published_at ?? ''
  }
}

export type ProgressFn = (percent: number, stage: UpdateProgress['stage'], message: string) => void

/**
 * Скачивает файл через curl и сообщает проценты.
 *
 * Проценты берём из вывода самого curl, а не выдумываем: он пишет ход дела
 * строками вида «12.3%», и их можно читать по мере поступления. execFile
 * отдаёт вывод только в конце, поэтому здесь spawn.
 */
async function download(url: string, destination: string, onProgress?: ProgressFn): Promise<void> {
  const args = [
    '-L', '-m', '600', '--fail',
    // «#» — короткая строка прогресса: одна на всё скачивание, без полосок
    '--progress-bar', '-o', destination, url
  ]
  const { spawn } = require('node:child_process') as typeof import('node:child_process')

  await new Promise<void>((resolve, reject) => {
    const child = spawn('curl.exe', args, { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] })
    let tail = ''
    let reported = 0

    child.stderr.on('data', (chunk: Buffer) => {
      tail += chunk.toString('utf8')
      // держим только хвост: строка прогресса перезаписывается через \r
      tail = tail.slice(-400)
      const match = tail.match(/(\d+(?:\.\d+)?)\s*%/)
      if (!match) return
      const percent = Math.min(100, Math.round(Number(match[1])))
      // сообщаем только о целом новом проценте: иначе событий будет тысяча
      if (percent <= reported) return
      reported = percent
      onProgress?.(percent, 'download', `скачивание ${percent}%`)
    })

    child.on('error', reject)
    child.on('close', (code: number) => {
      if (code === 0) {
        onProgress?.(100, 'download', 'скачивание завершено')
        resolve()
      } else {
        reject(new Error(`curl завершился с кодом ${code}`))
      }
    })
  })
}

/** Переносит текущую папку компонента в backups/, чтобы можно было откатиться. */
/** Сообщает интерфейсу, где обновление и сколько сделано. */
function report(target: UpdateProgress['target'], percent: number, stage: UpdateProgress['stage'], message: string): void {
  emit('update:progress', { target, percent, stage, message })
}

function backup(dir: string): void {
  try {
    if (!fs.existsSync(dir)) return
    fs.mkdirSync(BACKUPS_DIR, { recursive: true })
    const target = path.join(BACKUPS_DIR, `${path.basename(dir)}-${Date.now()}`)
    fs.renameSync(dir, target)
  } catch (error) {
    logger.write(`[updater] не удалось сделать резервную копию ${dir}: ${String(error)}`)
  }
}

/**
 * Ставит обновление компонента.
 *
 * Компоненты распространяются архивами: скачиваем архив, переносим старую
 * папку в резервную копию, распаковываем новую и возвращаем списки
 * пользователя на место — обновление не должно задевать то, что человек
 * дописал руками.
 */
export async function applyComponentUpdate(
  key: ComponentKey,
  zapret: ZapretComponent,
  tgws: TgWsComponent
): Promise<{ ok: boolean; message: string }> {
  const component = key === 'zapret' ? zapret : tgws
  // Обновляем туда, где пакет действительно лежит: иначе для пакета в папке
  // с другим именем свежая версия легла бы рядом, а программа продолжала бы
  // читать прежнюю — и показывала старую версию как установленную.
  const dir = key === 'zapret' ? zapret.dir : tgws.dir
  const say = (percent: number, stage: UpdateProgress['stage'], message: string) =>
    report(key, percent, stage, message)

  if (component.isRunning()) {
    const stopped = await component.stop()
    if (!stopped.ok) return { ok: false, message: 'не удалось остановить компонент' }
  }

  say(0, 'download', 'ищу релиз')
  const release = await latestRelease(REPOS[key])
  if (!release) {
    say(0, 'error', 'не удалось получить список файлов релиза')
    return { ok: false, message: 'не удалось получить список файлов релиза' }
  }

  // архив обновления: zip для zapret; у tg-ws-proxy архива нет вовсе
  const files = assets(release)
  const archiveAsset =
    files.find((asset) => /\.zip$/i.test(asset.name)) ??
    files.find((asset) => /\.(zip|7z|rar)$/i.test(asset.name))

  // ...но релиз tg-ws-proxy архива не содержит вовсе: там лежит один файл
  // TgWsProxy_windows.exe (рядом сборки для Linux, macOS и Windows 7 — их не
  // трогаем). Распаковывать нечего — кладём exe на место как есть. Раньше
  // такое обновление падало с «в релизе нет архива».
  const exeAsset =
    archiveAsset === undefined && key === 'tgws'
      ? files.find((asset) => asset.name === EXE_NAME) ?? files.find((asset) => /\.exe$/i.test(asset.name))
      : undefined
  const tmpRoot = tmpDir()
  const source = archiveAsset ?? exeAsset
  if (!source) {
    say(0, 'error', 'в релизе нет архива')
    return { ok: false, message: 'в релизе нет архива — откройте страницу релиза' }
  }
  const archive = path.join(tmpRoot, source.name)
  try {
    fs.mkdirSync(tmpRoot, { recursive: true })
    await download(source.browser_download_url, archive, (percent, stage, message) =>
      say(percent, stage, message)
    )

    // Списки адресов: сохраняем ВСЕ, какие есть, и возвращаем на место.
    //
    // Обновление zapret приносит свои versions списков — list-general.txt,
    // list-google.txt и остальные. Человек их правит руками (и через наш
    // редактор), и если после обновления его правки затираются свежими, вся
    // настройка уезжает: домены, которые он дописал, исчезают, а те, что он
    // убрал, возвращаются. Поэтому возвращаем человеку именно его файлы, а
    // новые списки релиза кладём рядом с ними.
    const savedLists = new Map<string, string>()
    if (key === 'zapret') {
      for (const name of zapret.listFiles()) {
        try {
          savedLists.set(name, zapret.readUserList(name))
        } catch {
          /* нечитаемый список не помеха */
        }
      }
    }

    backup(dir)
    fs.mkdirSync(dir, { recursive: true })

    if (exeAsset) {
      // exe не распаковывается: только переносим и даём ему то имя, под
      // которым компонент его ищет — иначе файл из GitHub с другим именем
      // лег бы в папку мёртвым грузом.
      fs.copyFileSync(archive, path.join(dir, EXE_NAME))
      // версия exe нигде не написана, поэтому запоминаем её сами — иначе
      // после обновления плашка продолжала бы предлагать то, что уже стоит
      tgws.recordVersion(release.tag_name.replace(/^v/, ''))
      fs.rmSync(archive, { force: true })
      logger.write(`[updater] ${key} обновлён до ${release.tag_name}`)
      say(100, 'done', `готово: ${release.tag_name}`)
      return { ok: true, message: `обновлено до ${release.tag_name}` }
    }

    say(100, 'unpack', 'распаковываю')
    const extractDir = path.join(tmpRoot, `extract-${key}-${Date.now()}`)
    fs.mkdirSync(extractDir, { recursive: true })
    await extract(archive, extractDir)

    // внутри архива может быть как сама папка, так и её содержимое
    const entries = fs.readdirSync(extractDir)
    const nested = entries.length === 1 ? path.join(extractDir, entries[0]) : extractDir
    copyRecursive(nested, dir)

    if (key === 'zapret') {
      // Списки по умолчанию — только для тех, которых у человека нет вовсе.
      zapret.ensureUserLists()
      for (const [name, text] of savedLists) {
        try {
          zapret.writeUserList(name, text)
        } catch {
          /* не записалось — человек увидит список по умолчанию */
        }
      }
      logger.write(`[updater] списки zapret возвращены на место: ${savedLists.size} файлов`)
    }

    fs.rmSync(archive, { force: true })
    fs.rmSync(extractDir, { recursive: true, force: true })
    logger.write(`[updater] ${key} обновлён до ${release.tag_name}`)
    say(100, 'done', `готово: ${release.tag_name}`)
    return { ok: true, message: `обновлено до ${release.tag_name}` }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    logger.write(`[updater] обновление ${key} не удалось: ${message}`)
    say(0, 'error', message)
    return { ok: false, message }
  }
}

/** Распаковка архива: Expand-Archive для zip, 7z, если он есть. */
async function extract(archive: string, destination: string): Promise<void> {
  const { execFile } = require('node:child_process') as typeof import('node:child_process')
  const { promisify } = require('node:util') as typeof import('node:util')
  const run = promisify(execFile)
  if (/\.zip$/i.test(archive)) {
    const script = `Expand-Archive -LiteralPath '${archive.replace(/'/g, "''")}' -DestinationPath '${destination.replace(/'/g, "''")}' -Force`
    await run('powershell.exe', ['-NoProfile', '-Command', script], { windowsHide: true, timeout: 300000 })
    return
  }
  await run('7z', ['x', `-o${destination}`, archive, '-y'], { windowsHide: true, timeout: 300000 })
}

function copyRecursive(source: string, destination: string): void {
  fs.mkdirSync(destination, { recursive: true })
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const from = path.join(source, entry.name)
    const to = path.join(destination, entry.name)
    if (entry.isDirectory()) copyRecursive(from, to)
    else fs.copyFileSync(from, to)
  }
}

/**
 * Обновление самой программы.
 *
 * exe занят, пока программа работает, поэтому скачиваем установщик,
 * останавливаем компоненты и запускаем его: установщик сам закроет нас и
 * поставит новую версию.
 */
export async function applyAppUpdate(): Promise<{ ok: boolean; message: string }> {
  const release = await latestRelease(APP_REPO)
  if (!release) return { ok: false, message: 'не удалось получить релиз' }
  const files = assets(release)
  const installer = files.find((asset) => /\.exe$/i.test(asset.name))
  if (!installer) {
    await shell.openExternal(release.html_url)
    return { ok: true, message: 'открыта страница релиза' }
  }
  const target = path.join(os.tmpdir(), installer.name)
  const say = (percent: number, stage: UpdateProgress['stage'], message: string) =>
    report('app', percent, stage, message)
  try {
    say(0, 'download', 'ищу установщик')
    await download(installer.browser_download_url, target, (percent, stage, message) =>
      say(percent, stage, message)
    )
    const { spawn } = require('node:child_process') as typeof import('node:child_process')
    spawn(target, ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true
    }).unref()
    say(100, 'done', 'установщик запущен')
    return { ok: true, message: 'установщик запущен, программа закроется' }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    say(0, 'error', message)
    return { ok: false, message }
  }
}
