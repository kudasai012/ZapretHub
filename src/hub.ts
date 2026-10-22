import type { HubApi } from '@shared/contract'

/**
 * Тип моста, который отдаёт preload.
 *
 * Живёт отдельным файлом без импортов из Electron: интерфейс собирается для
 * браузера и не должен видеть типы Node.
 */
export type Hub = HubApi
