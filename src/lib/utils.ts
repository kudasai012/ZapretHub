import { useCallback, useState } from 'react'
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Склеивает классы, разрешая конфликты Tailwind в пользу последнего. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/** Форматирует миллисекунды в «12 мс» или «—». */
export function formatMs(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '—'
  return `${Math.round(ms)} мс`
}

/**
 * Сворачивали панель или нет — и это запоминается.
 *
 * Свёрнутая панель компонента — это выбор человека, а не состояние раздела:
 * он прячет TG WS Proxy, уходит на другую страницу, возвращается — и панель
 * должна остаться свёрнутой. Раньше состояние жило только в памяти React и
 * терялось при каждом переходе, и человек проделывал одну и ту же работу заново.
 *
 * Храним в localStorage, а не в файле настроек: это чисто вид экрана, его не
 * нужно ни пересылать, ни сбрасывать вместе с настройками, а localStorage
 * доступен сразу и без запроса к главному процессу.
 */
export function useRemembered(key: string, fallback: boolean): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const stored = window.localStorage.getItem(key)
      return stored === null ? fallback : stored === '1'
    } catch {
      // приватный режим или закрытое хранилище: работаем без памяти
      return fallback
    }
  })

  const remember = useCallback((next: boolean) => {
    setValue(next)
    try {
      window.localStorage.setItem(key, next ? '1' : '0')
    } catch {
      /* запомнить не смогли — не беда, свёрнутость подействует до перезапуска */
    }
  }, [key])

  return [value, remember]
}
