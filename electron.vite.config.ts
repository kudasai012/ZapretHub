import { resolve } from 'node:path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: 'out/main',
      rollupOptions: { input: { index: resolve(__dirname, 'electron/main/index.ts') } }
    },
    resolve: { alias: { '@shared': resolve(__dirname, 'shared') } }
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: { outDir: 'out/preload', lib: { entry: resolve(__dirname, 'electron/preload/index.ts'), formats: ['cjs'] } },
    resolve: { alias: { '@shared': resolve(__dirname, 'shared') } }
  },
  renderer: {
    root: 'src',
    plugins: [react()],
    resolve: { alias: { '@': resolve(__dirname, 'src'), '@shared': resolve(__dirname, 'shared') } },
    build: {
      // outDir задаётся от корня проекта, а не от root
      outDir: 'out/renderer',
      emptyOutDir: true,
      rollupOptions: { input: { index: resolve(__dirname, 'src/index.html') } }
    }
  }
})
