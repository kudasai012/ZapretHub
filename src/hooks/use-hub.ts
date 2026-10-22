import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  AppConfig,
  DiagnosticsTargetResult,
  ErrorNotice,
  HomeState,
  TgwsState,
  UpdateProgress,
  ZapretState
} from '@shared/contract'
import { translate, type Lang } from '@/i18n'
import { toast } from '@/hooks/use-toast'

/**
 * Связка интерфейса с главным процессом.
 *
 * Держит состояние в одном месте и подписана на события: статус компонента
 * меняется в главном процессе, а интерфейс узнаёт о нём сам, без опроса.
 */

export function useLang(config: AppConfig | null): Lang {
  return config?.general.language ?? 'ru'
}

export function useT(lang: Lang) {
  return useCallback(
    (key: string, params?: Record<string, string | number>) => translate(lang, key, params),
    [lang]
  )
}

/** Конфиг с подпиской на сохранение. */
export function useConfig() {
  const [config, setConfig] = useState<AppConfig | null>(null)

  useEffect(() => {
    let alive = true
    void window.hub.config.get().then((value) => {
      if (alive) setConfig(value)
    })
    // Настройки мог изменить не этот вызов: без подписки тумблер оставался бы
    // в прежнем положении, хотя значение уже ушло в файл.
    const off = window.hub.on('config:changed', setConfig)
    return () => {
      alive = false
      off()
    }
  }, [])

  const save = useCallback(async (patch: Record<string, unknown>) => {
    const next = await window.hub.config.save(patch)
    setConfig(next)
    return next
  }, [])

  return { config, save, setConfig }
}

/**
 * Прогресс обновления с подпиской на события.
 *
 * Проценты настоящие: их считает curl, а интерфейсу остаётся рисовать.
 */
export function useUpdateProgress() {
  const [progress, setProgress] = useState<UpdateProgress | null>(null)

  useEffect(() => {
    const off = window.hub.on('update:progress', (value) => setProgress(value))
    return off
  }, [])

  /**
   * Готово или сорвалось — убираем запись сама.
   *
   * Раньше полоска «100%» висела в боковом меню вечно: главный процесс
   * присылал последнее состояние и больше не говорил ничего, а интерфейс
   * хранил его. Человек видел висющую строку установки над статусом и не
   * понимал, идёт дело или нет.
   */
  useEffect(() => {
    if (!progress) return
    const finished = progress.stage === 'done' || progress.stage === 'error'
    if (!finished) return
    // Небольшая задержка: строка «готово» должна успеть прочитаться глазами.
    const timer = setTimeout(() => setProgress(null), finished ? 3500 : 0)
    return () => clearTimeout(timer)
  }, [progress])

  return { progress, close: () => setProgress(null) }
}

/**
 * Очередь ошибок для отдельного окна.
 *
 * Ошибки приходят событиями, и за время чтения одной может прийти другая —
 * поэтому копим список и показываем по одной.
 */
export function useErrorNotices() {
  const [queue, setQueue] = useState<ErrorNotice[]>([])

  useEffect(() => {
    const off = window.hub.on('error:notice', (notice) => setQueue((list) => [...list, notice]))
    return off
  }, [])

  return {
    notice: queue[0] ?? null,
    count: queue.length,
    close: () => setQueue((list) => list.slice(1))
  }
}

/** Состояние компонентов с живой подпиской на события. */
export function useComponents() {
  const [home, setHome] = useState<HomeState | null>(null)
  const last = useRef<{ signature: string | null }>({ signature: null })

  /**
   * Опрос ради страховки: пять секунд.
   *
   * Настоящий источник правды — события, а не опрос. Но событие могло прийти
   * раньше подписки, и тогда без страховки экран остался бы с прежним
   * состоянием. Пять секунд для такой страховки с запасом: раньше стояло две,
   * и программа каждые две секунды просыпалась, перерисовывала весь интерфейс
   * и ела процессор у открытого окна, хотя на экране ничего не менялось.
   */
  const POLL_MS = 5000

  /**
   * Принять снимок на экран — но только если он правда другой.
   *
   * Опрос и события присылают снимок регулярно, и когда на экране ничего не
   * менялось, каждый такой снимок уходил в React и перерисовывал всё дерево:
   * боковое меню, страницу, всплывающие окна. Сравнение по тексту снимка
   * честное — любое расхождение видно, — а одинаковый снимок больше не стоит
   * ни одной перерисовки.
   */
  const apply = useCallback((snapshot: HomeState | null) => {
    if (!snapshot) return
    const signature = JSON.stringify(snapshot)
    if (signature === last.current.signature) return
    last.current.signature = signature
    setHome(snapshot)
  }, [])

  const refresh = useCallback(async () => {
    apply(await window.hub.home.snapshot())
  }, [apply])

  useEffect(() => {
    void refresh()
    const offHome = window.hub.on('home:state', apply)
    const offZapret = window.hub.on('zapret:state', () => void refresh())
    const offTgws = window.hub.on('tgws:state', () => void refresh())
    const offStatus = window.hub.on('component:status', () => void refresh())
    // страховка на случай, если событие пришло раньше подписки
    const poll = setInterval(() => void refresh(), POLL_MS)
    // Вернулись в окно — переспрашиваем. Снимок мог сняться в самый первый
    // миг, когда компоненты ещё не нашлись на диске, и «Компонент не
    // установлен» повисло бы до следующего события. Возврат фокуса — самый
    // дешёвый способ убедиться, что на экране правда.
    const wake = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    window.addEventListener('focus', wake)
    document.addEventListener('visibilitychange', wake)
    return () => {
      offHome()
      offZapret()
      offTgws()
      offStatus()
      clearInterval(poll)
      window.removeEventListener('focus', wake)
      document.removeEventListener('visibilitychange', wake)
    }
  }, [refresh, apply])

  return { home, refresh }
}

/** Состояние zapret: стратегии, Game Filter, IPSet, списки. */
export function useZapret() {
  const [state, setState] = useState<ZapretState | null>(null)

  const refresh = useCallback(async () => {
    setState(await window.hub.zapret.snapshot())
  }, [])

  useEffect(() => {
    void refresh()
    const off = window.hub.on('zapret:state', setState)
    return off
  }, [refresh])

  return { state, refresh, setState }
}

/** Состояние TG WS Proxy. */
export function useTgws() {
  const [state, setState] = useState<TgwsState | null>(null)

  const refresh = useCallback(async () => {
    setState(await window.hub.tgws.snapshot())
  }, [])

  useEffect(() => {
    void refresh()
    const off = window.hub.on('tgws:state', setState)
    return off
  }, [refresh])

  return { state, refresh, setState }
}

/**
 * Ход прогона стратегий.
 *
 * Прогон идёт в главном процессе, поэтому переживает переходы между разделами:
 * ушёл с диагностики и вернулся — прогон на месте, и кнопка «Прогнать» не
 * нажмётся поверх идущего. Раньше очередь перебирала сама страница, и при
 * уходе с раздела прогон обрывался на середине: результатов не было, а человек
 * запускал его заново.
 */
export function useDiagnostics() {
  const [results, setResults] = useState<Record<string, DiagnosticsTargetResult[]>>({})
  const [busy, setBusy] = useState(false)
  const [strategy, setStrategy] = useState<string | null>(null)
  const [done, setDone] = useState(0)
  const [total, setTotal] = useState(0)

  useEffect(() => {
    let alive = true
    void window.hub.diagnostics.status().then((value) => {
      if (!alive) return
      setBusy(value.busy)
      setStrategy(value.strategy)
      setDone(value.done)
      setTotal(value.total)
    })
    const offProgress = window.hub.on('strategy:progress', (payload) => {
      setResults((prev) => ({ ...prev, [payload.strategy]: payload.results }))
    })
    const offTick = window.hub.on('diagnostics:progress', (payload) => {
      setBusy(true)
      setStrategy(payload.strategy || null)
      setDone(payload.done)
      setTotal(payload.total)
    })
    const offDone = window.hub.on('diagnostics:done', (payload) => {
      setResults(payload.results)
      setBusy(false)
      setStrategy(null)
      setDone(0)
      setTotal(0)
    })
    return () => {
      alive = false
      offProgress()
      offTick()
      offDone()
    }
  }, [])

  /** Дописать результаты под своим именем: проверка без прогона стратегий. */
  const merge = useCallback((name: string, value: DiagnosticsTargetResult[]) => {
    setResults((prev) => ({ ...prev, [name]: value }))
  }, [])

  return { results, busy, strategy, done, total, merge }
}

/**
 * Выполняет действие и показывает результат всплывающим сообщением.
 *
 * Обёртка нужна, потому что почти каждое нажатие кнопки заканчивается либо
 * успехом, либо понятной причиной отказа — и повторять эту развилку в каждом
 * обработчике значит потерять половину текста.
 */
export function useAction(t: (key: string, params?: Record<string, string | number>) => string) {
  return useCallback(
    async <T,>(
      promise: Promise<T>,
      messages: { success?: string; failure?: string }
    ): Promise<T | null> => {
      try {
        const result = await promise
        if (messages.success) toast({ title: messages.success, variant: 'success' })
        return result
      } catch (error) {
        toast({
          title: messages.failure ?? t('common.error'),
          description: error instanceof Error ? error.message : String(error),
          variant: 'destructive'
        })
        return null
      }
    },
    [t]
  )
}
