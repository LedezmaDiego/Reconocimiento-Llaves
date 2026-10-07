import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries([
      '/solicitar_acceso', '/login', '/acceso_codigo', '/estado', '/modo',
      '/ultima_foto', '/guardar_foto', '/mis_fotos', '/foto', '/reconocimiento',
      '/retiro', '/devolucion', '/llaves',
      '^/admin/(login|usuarios|decidir|usuario)',
    ].map((path) => [path, backend])),
  },
})
