import type { ComponentSnapshot } from '@shared/contract'
import type { StatusTone } from '@/components/status-dot'

/**
 * Состояние обхода, рассказанное словами.
 *
 * Одно и то же состояние показывают крупная карта на главной и плашка внизу
 * бокового меню, поэтому сводят их в одно место: иначе надписи расходятся,
 * и в меню написано одно, а на главной — другое.
 */

/** Что делает крупная кнопка. */
export type MainAction = 'start' | 'stop' | 'install'

/** Состояние обхода целиком. */
export interface Verdict {
  /** Главная строка: что происходит. */
  headline: string
  /** Что именно не так, если не так. */
  detail: string
  tone: StatusTone
  action: MainAction
}

type Translate = (key: string, params?: Record<string, string | number>) => string

/** Короткое имя компонента: «Zapret» и «TG WS Proxy». */
export function componentName(t: Translate, key: string): string {
  return key === 'zapret' ? t('nav.zapret') : t('nav.tgws')
}

/**
 * Состояние одного компонента словами.
 *
 * Раньше было «Работает / Остановлен»: для упавшего компонента это звучало
 * как «Остановлен», и человек не видел, что запуск сорвался. Теперь
 * «не запустился» и причина говорят о проблеме прямо.
 */
export function stateText(t: Translate, snapshot: ComponentSnapshot): string {
  if (!snapshot.installed) return t('common.not_installed')
  const word = t(`home.state_${snapshot.status}`)
  const reason = snapshot.status === 'crashed' ? snapshot.reason.trim() : ''
  return reason ? `${word}, ${t('home.state_why', { reason })}` : word
}

/**
 * Сводит состояния компонентов в одну понятную фразу.
 *
 * Порядок важен: сначала авария, потом переходные состояния, потом работа,
 * и только в конце — «выключен». Иначе «останавливается» выглядело бы как
 * «работает», потому что один компонент ещё жив.
 */
export function verdictOf(t: Translate, parts: (ComponentSnapshot | null)[]): Verdict {
  const live = parts.filter((item): item is ComponentSnapshot => item !== null)
  if (live.length === 0) {
    return { headline: t('home.by_stopped'), detail: '', tone: 'stopped', action: 'start' }
  }

  const missing = live.filter((item) => !item.installed)
  const idle = live.filter((item) => item.installed && item.status !== 'running')
  const crashed = live.filter((item) => item.status === 'crashed')
  const running = live.filter((item) => item.status === 'running')

  const notes: string[] = []
  if (idle.length) {
    notes.push(t('home.by_detail', { list: idle.map((item) => componentName(t, item.key)).join(', ') }))
  }
  if (missing.length) {
    notes.push(t('home.by_detail_missing', { list: missing.map((item) => componentName(t, item.key)).join(', ') }))
  }

  // Авария: причина важнее списка, поэтому она идёт первой.
  const crashReason = crashed.find((item) => item.reason.trim())?.reason.trim() ?? ''
  if (crashed.length) {
    return {
      headline: t('home.by_failed'),
      detail: crashReason ? t('home.state_why', { reason: crashReason }) : notes.join(' · '),
      tone: 'crashed',
      action: 'start'
    }
  }

  if (live.some((item) => item.status === 'stopping')) {
    return { headline: t('home.by_stopping'), detail: '', tone: 'stopping', action: 'stop' }
  }
  if (live.some((item) => item.status === 'starting')) {
    return { headline: t('home.by_starting'), detail: '', tone: 'starting', action: 'start' }
  }

  // Ничего не работает: либо ещё нечего включать, либо просто выключено.
  if (running.length === 0) {
    return missing.length
      ? { headline: t('home.by_not_ready'), detail: notes.join(' · '), tone: 'stopped', action: 'install' }
      : { headline: t('home.by_stopped'), detail: '', tone: 'stopped', action: 'start' }
  }

  return running.length === live.length
    ? { headline: t('home.by_working'), detail: '', tone: 'running', action: 'stop' }
    : { headline: t('home.by_partial'), detail: notes.join(' · '), tone: 'starting', action: 'stop' }
}

/**
 * Обход сейчас запускают или гасят.
 *
 * Цвет точки этим не определить: у него своё дело — частично работающий обход
 * подсвечен тем же предупреждающим цветом, что и запускающийся. А команда во
 * время запуска или остановки собьёт её с толку, поэтому смотрим на состояния
 * самих компонентов.
 */
export function isTransitioning(parts: (ComponentSnapshot | null)[]): boolean {
  return parts.some((item) => item?.status === 'starting' || item?.status === 'stopping')
}

/** Кружок карты «Обход» подкрашивается в цвет состояния. */
export const CIRCLE_CLASS: Record<StatusTone, string> = {
  running: 'bg-success/15 text-success',
  starting: 'bg-warning/15 text-warning',
  stopping: 'bg-warning/15 text-warning',
  crashed: 'bg-destructive/15 text-destructive',
  stopped: 'bg-muted text-muted-foreground'
}
