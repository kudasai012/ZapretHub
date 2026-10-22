/**
 * Журнал программы.
 *
 * Пишет в data/logs/hub.log с ротацией по размеру: два файла по 2 МБ, иначе
 * при постоянно работающем winws лог за вечер разрастается до сотен
 * мегабайт и занимает весь диск.
 */
import fs from 'node:fs'
import path from 'node:path'
import { HUB_LOG_FILE, LOGS_DIR } from './paths'

const MAX_LOG_BYTES = 2 * 1024 * 1024
const LOG_BACKUPS = 2

export class Logger {
  private readonly file: string

  constructor(file: string = HUB_LOG_FILE) {
    this.file = file
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true })
    } catch {
      /* папку создаст первая запись */
    }
  }

  /** Дописывает строку с отметкой времени. */
  write(line: string): void {
    const stamp = new Date().toISOString().replace('T', ' ').slice(0, 19)
    try {
      this.rotateIfNeeded()
      fs.appendFileSync(this.file, `[${stamp}] ${line}\n`, 'utf8')
    } catch {
      /* журнал не должен ронять программу */
    }
  }

  /** Дописывает строку в отдельный файл внутри logs/. */
  writeTo(name: string, line: string): void {
    try {
      const target = path.join(LOGS_DIR, name)
      fs.appendFileSync(target, `${line}\n`, 'utf8')
    } catch {
      /* см. выше */
    }
  }

  private rotateIfNeeded(): void {
    try {
      if (!fs.existsSync(this.file)) return
      if (fs.statSync(this.file).size <= MAX_LOG_BYTES) return
      for (let i = LOG_BACKUPS; i > 0; i -= 1) {
        const src = `${this.file}.${i}`
        const dst = `${this.file}.${i + 1}`
        if (fs.existsSync(src)) fs.renameSync(src, dst)
      }
      fs.renameSync(this.file, `${this.file}.1`)
    } catch {
      /* не смогли — пишем дальше в тот же файл */
    }
  }
}

export const logger = new Logger()
