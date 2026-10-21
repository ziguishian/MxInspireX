import { createServer, type Server } from 'node:net';
import { afterEach, describe, expect, it } from 'vitest';
import { chooseApiPort } from './apiPort.js';

const servers: Server[] = [];

afterEach(async () => {
  await Promise.all(servers.splice(0).map((server) => new Promise<void>((resolve) => server.close(() => resolve()))));
});

async function occupyEphemeralPort(): Promise<number> {
  const server = createServer();
  servers.push(server);
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('测试端口分配失败');
  return address.port;
}

describe('desktop API port policy', () => {
  it('keeps development on the browser-visible port when it is available', async () => {
    const temporary = createServer();
    await new Promise<void>((resolve, reject) => {
      temporary.once('error', reject);
      temporary.listen(0, '127.0.0.1', resolve);
    });
    const address = temporary.address();
    if (!address || typeof address === 'string') throw new Error('测试端口分配失败');
    const port = address.port;
    await new Promise<void>((resolve) => temporary.close(() => resolve()));

    await expect(chooseApiPort(port, false)).resolves.toBe(port);
  });

  it('reports a fixed development-port conflict instead of silently switching ports', async () => {
    const occupied = await occupyEphemeralPort();
    await expect(chooseApiPort(occupied, false)).rejects.toThrow(`本地 API 端口 ${occupied} 已被占用`);
  });

  it('still permits a random fallback for packaged desktop sessions', async () => {
    const occupied = await occupyEphemeralPort();
    const selected = await chooseApiPort(occupied, true);
    expect(selected).toBeGreaterThan(0);
    expect(selected).not.toBe(occupied);
  });
});
