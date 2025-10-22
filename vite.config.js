// vite.config.js
import { defineConfig } from 'vite';

export default defineConfig(({ command }) => ({
  // ważne dla GitHub Pages pod repo "cleaning-dashboard"
  base: '/cleaning-dashboard/',
  // proxy tylko lokalnie
  server: command === 'serve'
    ? {
        proxy: {
          '/gios': {
            target: 'https://api.gios.gov.pl',
            changeOrigin: true,
            secure: true,
            rewrite: p => p.replace(/^\/gios/, ''),
          },
        },
      }
    : undefined,
  build: { outDir: 'dist' }
}));
