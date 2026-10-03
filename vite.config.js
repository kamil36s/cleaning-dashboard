// vite.config.js
import { resolve } from 'node:path';
import { readFileSync } from 'node:fs';
import { defineConfig } from 'vite';

const FINANCE_PRIVATE_PATH = /^\/(?:cleaning-dashboard\/)?data\/(?:budget\.json|finance\.sqlite(?:-(?:wal|shm))?|mental-health\.sqlite(?:-(?:wal|shm))?|jobhunt(?:\.sqlite(?:-(?:wal|shm))?|\/)|\.finance-account-key|budget-backups\/|backups\/|finance-imports\/|finance-receipts\/|settings\/bills\.json)/i;
const LANGUAGE_PRIVATE_PATH = /^\/(?:cleaning-dashboard\/)?(?:data\/(?:language-learning(?:\.sqlite(?:-(?:wal|shm))?|\/)|reference\/|audio\/language-learning\/|backups\/)|language_learning\/benchmark_content\/)/i;
const PHONE_PRIVATE_PATH = /^\/(?:cleaning-dashboard\/)?data\/phone-tracker\.sqlite(?:-(?:wal|shm))?$/i;
const PRIVATE_SOURCE_PATH = /(?:^|\/)(?:\.env(?:\.[^/]*)?|[^/]+\.(?:sqlite(?:-(?:wal|shm))?|db(?:-(?:wal|shm))?|py))$/i;

export function financePrivacyPlugin() {
  const denyFinanceFiles = (server) => {
    server.middlewares.use((request, response, next) => {
      let path;
      try {
        path = decodeURIComponent(new URL(request.url || '/', 'http://localhost').pathname);
      } catch {
        response.statusCode = 400;
        response.end('Bad request');
        return;
      }
      if (!FINANCE_PRIVATE_PATH.test(path) && !LANGUAGE_PRIVATE_PATH.test(path) && !PHONE_PRIVATE_PATH.test(path)
          && !PRIVATE_SOURCE_PATH.test(path) && !/(?:^|\/)benchmark_content(?:\/|$)/i.test(path)) return next();
      response.statusCode = 404;
      response.end('Not found');
    });
  };
  return {
    name: 'finance-runtime-privacy',
    configureServer: denyFinanceFiles,
    configurePreviewServer: denyFinanceFiles,
  };
}

export function historyWikiStaticAssetsPlugin() {
  const emitLocalAsset = (context, sourcePath, fileName) => {
    context.emitFile({
      type: 'asset',
      fileName,
      source: readFileSync(resolve(process.cwd(), sourcePath)),
    });
  };
  return {
    name: 'history-wiki-static-assets',
    generateBundle() {
      emitLocalAsset(this, 'apps/history-wiki/history-wiki.js', 'apps/history-wiki/history-wiki.js');
      emitLocalAsset(this, 'apps/history-wiki/data/history-wiki-data.js', 'apps/history-wiki/data/history-wiki-data.js');
    },
  };
}

export default defineConfig(({ command }) => ({
  // ważne dla GitHub Pages pod repo "cleaning-dashboard"
  base: '/cleaning-dashboard/',
  plugins: [financePrivacyPlugin(), historyWikiStaticAssetsPlugin()],
  // proxy tylko lokalnie
  server: command === 'serve'
    ? {
        proxy: {
          '/api': {
            target: 'http://127.0.0.1:8000',
            // Keep the browser-facing LAN host so same-origin write checks in
            // server.py also work for clients using http://PC-IP:5173.
            changeOrigin: false,
            secure: false,
          },
          '/gios': {
            target: 'https://api.gios.gov.pl',
            changeOrigin: true,
            secure: true,
            rewrite: p => p.replace(/^\/gios/, ''),
          },
        },
      }
    : undefined,
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        index: resolve(process.cwd(), 'index.html'),
        calendar: resolve(process.cwd(), 'calendar.html'),
        cleaning: resolve(process.cwd(), 'cleaning.html'),
        budget: resolve(process.cwd(), 'budget.html'),
        bloodPressure: resolve(process.cwd(), 'blood-pressure.html'),
        voiceJournal: resolve(process.cwd(), 'voice-journal.html'),
        journal: resolve(process.cwd(), 'journal.html'),
        journalOcr: resolve(process.cwd(), 'journal-ocr.html'),
        reading: resolve(process.cwd(), 'reading.html'),
        synchrobook: resolve(process.cwd(), 'synchrobook.html'),
        kitchen: resolve(process.cwd(), 'kitchen.html'),
        football: resolve(process.cwd(), 'football.html'),
        hitchen: resolve(process.cwd(), 'hitchen.html'),
        settings: resolve(process.cwd(), 'settings.html'),
        todayDisplay: resolve(process.cwd(), 'today-display.html'),
        heartRateHistory: resolve(process.cwd(), 'heart-rate-history.html'),
        sensors: resolve(process.cwd(), 'sensors.html'),
        aiUsage: resolve(process.cwd(), 'ai-usage.html'),
        phoneActivity: resolve(process.cwd(), 'phone-activity.html'),
        mentalHealth: resolve(process.cwd(), 'mental-health.html'),
        sleep: resolve(process.cwd(), 'sleep.html'),
        ring: resolve(process.cwd(), 'ring.html'),
        liveWorkout: resolve(process.cwd(), 'live-workout.html'),
        santiagoRouteQa: resolve(process.cwd(), 'santiago-route-qa.html'),
        developerDocs: resolve(process.cwd(), 'developer-docs.html'),
        jobhunt: resolve(process.cwd(), 'jobhunt.html'),
        todo: resolve(process.cwd(), 'todo.html'),
        timeline: resolve(process.cwd(), 'timeline.html'),
        historyWiki: resolve(process.cwd(), 'apps/history-wiki/index.html'),
        music: resolve(process.cwd(), 'music.html'),
        language: resolve(process.cwd(), 'language.html'),
        brutalAssault2027: resolve(process.cwd(), 'brutal-assault-2027.html'),
        rymPolishBlackMetalTop100: resolve(process.cwd(), 'rym-polish-black-metal-top-100.html'),
        classicalLibrary: resolve(process.cwd(), 'classical-library.html'),
        spotifyScreensaver: resolve(process.cwd(), 'spotify-screensaver.html'),
        artistFactsScreensaver: resolve(process.cwd(), 'artist-facts-screensaver.html'),
      },
    },
  }
}));
