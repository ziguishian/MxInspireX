import { createServer } from 'node:net';

export async function chooseApiPort(preferred: number, allowRandomFallback = true): Promise<number> {
  const bind = (port: number) => new Promise<number>((resolve, reject) => {
    const probe = createServer();
    probe.once('error', reject);
    probe.listen(port, '127.0.0.1', () => {
      const address = probe.address();
      if (!address || typeof address === 'string') {
        probe.close();
        reject(new Error('无法分配本地 API 端口'));
        return;
      }
      probe.close((error) => error ? reject(error) : resolve(address.port));
    });
  });

  try {
    return await bind(preferred);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EADDRINUSE') throw error;
    if (!allowRandomFallback) {
      throw new Error(`本地 API 端口 ${preferred} 已被占用。请关闭占用进程，或在复用已有 API 时设置 AICS_SKIP_SIDECAR=1。`);
    }
    return bind(0);
  }
}
