import { describe, it, expect } from 'vitest';
import { directNodeCall, literalNode } from '../app/node_prompt.mjs';
import { selectProjectFrame, prepareModelInput } from '../app/sdk_context.mjs';
import { singleImageFrame } from '../app/execution_efficiency.mjs';
describe('literal node routing', () => {
  it('keeps optional template candidates in both conversation contexts', () => {
    const promptTemplates = {candidates:[{id:'one',text:'参考',kind:'image',styles:[],source:'user'}],trust:'reference_only'};
    expect(selectProjectFrame({promptTemplates}, 10000).promptTemplates).toEqual(promptTemplates);
    expect(singleImageFrame({promptTemplates}).promptTemplates).toEqual(promptTemplates);
  });
  it('preserves the literal node frame including parameters', () => {
    const frame = {nodePrompt:{version:1,submitted:' 原文\n'},canvasParams:{model:'chosen',kind:'html'}};
    const result = prepareModelInput({input:[]},{frame});
    const encoded = JSON.stringify(result);
    expect(encoded).toContain('chosen');
    expect(encoded).toContain('nodePrompt');
  });
  it('uses an exact prompt without invoking an agent for media', () => {
    for (const kind of ['image', 'upload', 'video', 'audio']) {
      const call = directNodeCall({taskSurface:'canvas_node', nodePrompt:{version:1,submitted:' 原文\n'},canvasParams:{kind}});
      expect(call.args.prompt).toBe(' 原文\n');
      expect(call.name).toBe(`generate_${kind === 'upload' ? 'image' : kind}`);
    }
  });
  it('keeps legacy tasks and content generation separate', () => {
    expect(directNodeCall({taskSurface:'canvas_node',canvasParams:{kind:'image'}})).toBeNull();
    expect(literalNode({taskSurface:'conversation',nodePrompt:{version:1}})).toBe(false);
    expect(directNodeCall({taskSurface:'canvas_node',nodePrompt:{version:1},canvasParams:{kind:'html'}})).toBeNull();
  });
});
