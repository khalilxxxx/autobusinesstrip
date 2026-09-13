import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/ui/',
  plugins: [react()],
  server: {
    proxy: {
      '/assistant/api': 'http://127.0.0.1:8766',
      '/mock/v1': 'http://127.0.0.1:8766',
    },
  },
});
