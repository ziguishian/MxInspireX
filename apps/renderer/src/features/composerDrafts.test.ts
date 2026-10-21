import { expect, it } from 'vitest';

it('unwraps reactive queued drafts for IndexedDB without losing binary attachments', async () => {
  const { reactive } = await import('vue');
  const { draftStorageValue } = await import('./composerDrafts');
  const file = new Blob(['original attachment'], { type: 'text/plain' });
  const queued = reactive([{ id: 'stable-id', draft: { files: [file], assets: [{ id: 'source' }] } }]);
  const edited = queued.map(item => ({ ...item, draft: { ...item.draft, text: 'edited' } }));
  const saved = structuredClone(draftStorageValue(edited));
  expect(saved[0].id).toBe('stable-id');
  expect(await saved[0].draft.files[0].text()).toBe('original attachment');
  expect(saved[0].draft.assets[0].id).toBe('source');
});
