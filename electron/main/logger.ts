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

/**
 * Предел для журналов компонентов.
 *
 * Вывод winws льётся непрерывно, и за несколько дней без обрезки файл
 * вырастает до сотен мегабайт: он лежит в папке программы, занимает диск и
 * не открывается ни одним блокнотом.
 */
const MAX_COMPONENT_BYTES = 2 * 1024 * 1024

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
      this.rotate(target, MAX_COMPONENT_BYTES, 1)
      fs.appendFileSync(target, `${line}\n`, 'utf8')
    } catch {
      /* см. выше */
    }
  }

  /**
   * Обрезает файл, если он перерос предел.
   *
   * Проверка по размеру, а не по дате: журнал компонента может набрать
   * предел за вечер, а может не набрать его за месяц — человеку важно, чтобы
   * файл открывался, а не чтобы он был свежим.
   */
  private rotate(target: string, maxBytes: number, backups: number): void {
    try {
      if (!fs.existsSync(target)) return
      if (fs.statSync(target).size <= maxBytes) return
      // Самую старую копию выбрасываем: она всё равно за пределами счёта.
      fs.rmSync(`${target}.${backups + 1}`, { force: true })
      for (let i = backups; i > 0; i -= 1) {
        const src = `${target}.${i}`
        if (!fs.existsSync(src)) continue
        fs.renameSync(src, `${target}.${i + 1}`)
      }
      fs.renameSync(target, `${target}.1`)
    } catch {
      /* не смогли — пишем дальше в тот же файл */
    }
  }

  private rotateIfNeeded(): void {
    this.rotate(this.file, MAX_LOG_BYTES, LOG_BACKUPS)
  }
}

export const logger = new Logger()
