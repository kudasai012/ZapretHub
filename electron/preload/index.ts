/**
 * Мост между интерфейсом и главным процессом.
 *
 * Интерфейс получает один объект `hub` с методами, сгруппированными по
 * смыслу: hub.config.save(...), hub.process.start('zapret'). Настоящего
 * доступа к Node у него нет: contextIsolation включён, nodeIntegration
 * выключен, и наружу торчит только этот мост.
 *
 * Каналы IPC плоские ('config:save'), а наружу — дерево: это позволяет
 * главному процессу оставаться простым, а интерфейсу — читаемым.
 */
import { contextBridge, ipcRenderer } from 'electron'
import type { HubApi, MainEvents } from '@shared/contract'

/** Имена каналов, на которые интерфейс подписывается. */
const EVENT_CHANNELS = [
  'component:status',
  'component:log',
  'zapret:state',
  'tgws:state',
  'home:state',
  'strategy:progress',
  'strategy:done',
  'diagnostics:progress',
  'diagnostics:done',
  'update:available',
  'app-update:available',
  'toast',
  'window:maximized',
  'config:changed',
  'update:progress',
  'error:notice'
] as const satisfies readonly (keyof MainEvents)[]

/**
 * Разворачивает плоский канал в вызов ipcRenderer.invoke.
 *
 * Если главный процесс ответил ошибкой, отдаём её наружу как исключение:
 * иначе в интерфейсе появлялся бы «undefined», и непонятно было, что сломалось.
 */
function channel(name: string) {
  return async (...args: unknown[]): Promise<unknown> => {
    const result = await ipcRenderer.invoke(name, ...args)
    if (result && typeof result === 'object' && '__error' in (result as Record<string, unknown>)) {
      throw new Error(String((result as Record<string, unknown>).__error))
    }
    return result
  }
}

/** Группы методов: имя группы в интерфейсе -> префикс канала. */
const GROUPS: Record<string, readonly string[]> = {
  config: ['get', 'save'],
  home: ['snapshot'],
  zapret: ['snapshot', 'setStrategy', 'setGameFilter', 'setIpsetMode', 'lists', 'readList', 'writeList', 'commandLine', 'removeService'],
  tgws: ['snapshot', 'saveSettings'],
  process: ['start', 'stop', 'startAll', 'stopAll'],
  diagnostics: ['targets', 'saveTargets', 'checkOne', 'testStrategy', 'checkAll', 'probeAll', 'status', 'runQueue', 'stop'],
  sysdiag: ['run', 'fix'],
  updates: ['check', 'apply'],
  // 'apply' здесь обязателен: без него кнопка «Обновить сейчас» в окне релиза
  // зовёт undefined и молча ничего не делает — контракт метод объявляет, а мост
  // его не отдаёт.
  'app-update': ['check', 'apply'],
  shell: ['openPath', 'openUrl'],
  window: ['minimize', 'close', 'isMaximized', 'toggleMaximize'],
  app: ['version', 'restart']
}

const api: Record<string, unknown> = {}

for (const [group, methods] of Object.entries(GROUPS)) {
  const target: Record<string, unknown> = {}
  for (const method of methods) {
    // 'app-update:check' -> группа 'app-update', а в интерфейсе appUpdate
    const channelName = `${group}:${method}`
    target[method] = channel(channelName)
  }
  api[group === 'app-update' ? 'appUpdate' : group] = target
}

api.on = <K extends keyof MainEvents>(channel_: K, listener: (payload: MainEvents[K]) => void) => {
  const wrapped = (_event: Electron.IpcRendererEvent, payload: unknown): void => {
    listener(payload as MainEvents[K])
  }
  ipcRenderer.on(channel_, wrapped)
  return () => {
    ipcRenderer.off(channel_, wrapped)
  }
}

// Приведение через unknown: api собран динамически из таблицы GROUPS, и
// TypeScript не может проверить совпадение сам. Контракт выше — источник
// истины, а таблица GROUPS обязана ему соответствовать.
contextBridge.exposeInMainWorld('hub', api as unknown as HubApi)

void EVENT_CHANNELS
