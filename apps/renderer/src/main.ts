import { createApp } from 'vue';
import BrandLoading from './components/BrandLoading.vue';
import { router, initialDesktopPath } from './router';
import './style.css';
import { startDeliveryWorker } from './deliveryWorker';
import { printConsoleEasterEgg } from './features/consoleEasterEgg';

const workerOnly = new URLSearchParams(location.search).get('deliveryWorker') === '1';
const stopDeliveryWorker = workerOnly || !window.studio?.isDesktop ? startDeliveryWorker(window.studio?.apiBaseUrl || 'http://127.0.0.1:8765') : undefined;
import.meta.hot?.dispose(() => stopDeliveryWorker?.());

async function mountStudio() {
  const loading = createApp(BrandLoading, { fullscreen: true });
  loading.mount('#app');
  try {
    const { default: App } = await import('./App.vue');
    const app = createApp(App);
    app.use(router);
    await router.isReady();
    if (initialDesktopPath && initialDesktopPath !== router.currentRoute.value.fullPath) await router.replace(initialDesktopPath);
    loading.unmount();
    app.mount('#app');
  } catch (error) {
    loading.unmount();
    const root = document.querySelector('#app');
    if (root) root.textContent = '加载失败，请重新打开应用。';
    console.error(error);
  }
}
if (!workerOnly) {
  printConsoleEasterEgg();
  void mountStudio();
}
