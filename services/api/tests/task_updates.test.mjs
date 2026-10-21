import { expect, it } from 'vitest';
import { TaskUpdateReader } from '../app/task_updates.mjs';
it('preserves steering across model calls and recovery, without rewriting canonical SDK input', async () => {
  let acknowledged = 0;
  const updates = [{ id: 'one', text: '不要蓝色，改用绿色', revision: 1 }];
  const reader = new TaskUpdateReader({ supportsTaskUpdates: true, baseUrl: 'http://fixture.invalid', projectId: 'p', taskId: 't' }, async (url, options) => {
    if (url.endsWith('acknowledge')) { acknowledged = JSON.parse(options.body).revision; return Response.json(updates); }
    return Response.json(updates);
  });
  const canonical = { input: [{ role: 'user', content: '原需求' }] };
  await reader.refresh(); await reader.acknowledge();
  expect(reader.apply(canonical).input.at(-1).content[0].text).toContain('改用绿色');
  expect(canonical.input).toHaveLength(1);
  expect(acknowledged).toBe(1);
  await reader.refresh();
  expect(reader.apply(canonical).input.at(-1).content[0].text).toContain('改用绿色');
});
it('fails closed when current steering cannot be read', async () => {
  const reader = new TaskUpdateReader({ supportsTaskUpdates: true, baseUrl: 'http://fixture.invalid', projectId: 'p', taskId: 't' }, async () => new Response('', { status: 503 }));
  await expect(reader.refresh()).rejects.toThrow('暂停');
});
