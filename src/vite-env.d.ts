/// <reference types="vite/client" />
declare global {
  interface Window {
    hub: import('./hub').Hub
  }
}
export {}
