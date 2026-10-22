import * as React from 'react'
type ToastVariant = 'default' | 'success' | 'warning' | 'destructive'

interface ToastState {
  id: string
  title: string
  description?: string
  variant: ToastVariant
  open: boolean
}

type Listener = (state: ToastState[]) => void

const listeners = new Set<Listener>()
let state: ToastState[] = []
let counter = 0

function emit(): void {
  for (const listener of listeners) listener(state)
}

function dismiss(id: string): void {
  state = state.map((toast) => (toast.id === id ? { ...toast, open: false } : toast))
  emit()
  setTimeout(() => {
    state = state.filter((toast) => toast.id !== id)
    emit()
  }, 200)
}

/** Показывает всплывающее сообщение. Живёт вне дерева React: зови из любого места. */
function toast(input: { title: string; description?: string; variant?: ToastVariant }): string {
  const id = `toast-${++counter}`
  state = [
    ...state,
    { id, title: input.title, description: input.description, variant: input.variant ?? 'default', open: true }
  ]
  emit()
  setTimeout(() => dismiss(id), 4200)
  return id
}

export function useToast(): {
  toasts: ToastState[]
  toast: typeof toast
  dismiss: (id: string) => void
} {
  const [toasts, setToasts] = React.useState<ToastState[]>(state)
  React.useEffect(() => {
    listeners.add(setToasts)
    setToasts(state)
    return () => {
      listeners.delete(setToasts)
    }
  }, [])
  return { toasts, toast, dismiss }
}

export { toast }
