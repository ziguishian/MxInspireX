import { describe, expect, it } from 'vitest';
import { messageReferences } from './messageReferences';
import { referenceSegments } from './references';

describe('sent message references', () => {
  const name = 'agent-image-fd0200bfd31346099989c79d4029669b.png';
  const defaults = { projectId: 'project', apiBaseUrl: 'http://local', assets: [{ id: 'image', projectId: 'project', pathRelative: `assets/${name}`, kind: 'image' }], documents: [], nodes: [] };
  it('renders a text node reference as one token with its title and text available for preview', () => {
    const text = '@node:brief-123 请细化方案';
    const refs = messageReferences({ ...defaults, text, nodes: [{ id: 'brief-123', data: { kind: 'text', title: '概念方案与落地框架', text: '礼盒采用杭州经典产业的文化元素。' } }] });
    expect(refs).toHaveLength(1);
    expect(refs[0]).toMatchObject({ key: 'node:brief-123', token: '@node:brief-123', kind: '文本', label: '概念方案与落地框架', textContent: '礼盒采用杭州经典产业的文化元素。' });
    expect(referenceSegments(text, refs).map(part => part.text).join('')).toBe(text);
    expect(referenceSegments(text, refs)[0].reference).toBe(refs[0]);
  });
  it('keeps restored node tokens compact before their canvas data arrives', () => {
    const refs = messageReferences({ ...defaults, text: '@node:loading-node' });
    expect(refs[0]).toMatchObject({ key: 'node:loading-node', token: '@node:loading-node', label: '引用节点', kind: '文本' });
    expect(refs[0].textContent).toBeUndefined();
  });
  it('renders both stable IDs and legacy filenames without rewriting the message', () => {
    for (const token of ['@asset:image', `@${name}`]) {
      const text = `${token} 为这个场景创作视频`;
      const refs = messageReferences({ ...defaults, text });
      expect(refs).toHaveLength(1);
      expect(refs[0].preview).toBe('http://local/api/projects/project/assets/image/content');
      const parts = referenceSegments(text, refs);
      expect(parts[0].reference?.label).toBe(name);
      expect(parts.filter(part => !part.reference).map(part => part.text).join('')).toBe(' 为这个场景创作视频');
      expect(parts.map(part => part.text).join('')).toBe(text);
    }
  });
  it('keeps @1 tied to each message even after the composer has different files', () => {
    const messages = ['first', 'second'].map(documentId => messageReferences({ ...defaults, text: '@1 请参考', snapshot: { referencedFiles: [{ documentId, filename: `${documentId}.png`, mime: 'image/png', index: 1, projectId: 'project' }] } }));
    expect(messages.map(refs => refs[0].preview)).toEqual(['first', 'second'].map(id => `http://local/api/projects/project/knowledge/documents/${id}/content`));
    expect(messages.map(refs => referenceSegments('@1 请参考', refs)[0].reference?.label)).toEqual(['first.png', 'second.png']);
  });
  it('resolves cross-project assets from the saved scope, not the current project', () => {
    const refs = messageReferences({ ...defaults, text: '@asset:remote', assets: [], snapshot: { referencedAssets: [{ id: 'remote', projectId: 'source project', filename: '图片.png' }] } });
    expect(refs[0].preview).toBe('http://local/api/projects/source%20project/assets/remote/content');
  });
  it('recognizes global image documents whose display titles have no extension', () => {
    const refs = messageReferences({ ...defaults, text: '@knowledge:doc', documents: [{ id: 'doc', title: '参考图', pathRelative: 'knowledge/documents/doc-reference.png' }], snapshot: { referencedFiles: [{ documentId: 'doc', scope: 'global', filename: '参考图' }] } });
    expect(refs[0]).toMatchObject({ preview: 'http://local/api/knowledge/documents/doc/content', kind: '图像' });
  });
  it('keeps attachments without tokens, uses type cards for documents and excludes unrelated assets', () => {
    const refs = messageReferences({ ...defaults, text: '分析附件', snapshot: { referencedFiles: [{ documentId: 'brief', filename: '设计要求.pdf', index: 1 }] } });
    expect(refs).toHaveLength(1);
    expect(refs[0]).toMatchObject({ attached: true, kind: 'PDF', label: '设计要求.pdf' });
    expect(refs[0].preview).toBeUndefined();
  });
  it('falls back to a compact card when an older asset has gone missing', () => {
    const refs = messageReferences({ ...defaults, text: '@asset:missing 继续', assets: [] });
    expect(referenceSegments('@asset:missing 继续', refs)[0].reference?.label).toBe('引用素材');
    expect(refs[0].preview).toBeUndefined();
  });
  it('does not guess same-named assets or partially consume @12', () => {
    const refs = messageReferences({ ...defaults, text: `@${name}`, assets: [...defaults.assets, { ...defaults.assets[0], id: 'other' }] });
    expect(refs).toEqual([]);
    const files = messageReferences({ ...defaults, text: '@12', snapshot: { referencedFiles: [{ filename: 'one.png', documentId: 'one', index: 1 }] } });
    expect(referenceSegments('@12', files)).toEqual([{ text: '@12' }]);
  });
});
