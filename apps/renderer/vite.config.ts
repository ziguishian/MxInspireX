import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ mode }) => ({
  root: fileURLToPath(new URL('.', import.meta.url)),
  // Web history needs root-relative assets when a deep link is refreshed.
  // The packaged desktop renderer still resolves files beside index.html.
  base: mode === 'desktop' ? './' : '/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@contracts': fileURLToPath(new URL('../../packages/contracts', import.meta.url)),
    },
  },
  server: {
    // Keep local development on IPv4. Some macOS sandboxed environments
    // reject Vite's default IPv6 ::1 listener even though localhost resolves
    // successfully for the browser.
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: mode === 'desktop' ? '../../dist/renderer' : '../../dist/web',
    emptyOutDir: true,
    // Three.js and GLTFLoader are intentionally lazy-loaded; keep the
    // initial workspace bundle small while allowing the optional 3D chunk.
    chunkSizeWarningLimit: 650,
  },
}));
