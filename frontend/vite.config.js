import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // доступно для ngrok / локальной сети
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Прямые прокси на эндпоинты бэкенда для локальной разработки
      '/me': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/legal': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/couple': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/conflict': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/mood': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/signal': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
