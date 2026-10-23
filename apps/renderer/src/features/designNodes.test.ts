import { cutoutModel } from './designNodes';
import { describe, it, expect } from 'vitest';
import { connectedReferences, canvasReferenceParams } from './canvasReferences';
describe('editable design constraints',()=>{
  it('uses current palette after edits and removes it after disconnect',()=>{
    const nodes=[{id:'p',data:{kind:'text',editor:'palette',colors:['#FF0000'],text:'stale'}}];
    const edges=[{id:'e',source:'p',target:'image'}];
    expect(connectedReferences('image',nodes,edges,'','')[0].text).toContain('#FF0000');
    nodes[0].data.colors=['#00FF00'];
    expect(connectedReferences('image',nodes,edges,'','')[0].text).toContain('#00FF00');
    expect(connectedReferences('image',nodes,[],'','')).toEqual([]);
  });
  it('binds ordered scenes and total duration to one video, preserving frame inputs',()=>{
    const nodes=[{id:'s',data:{kind:'text',editor:'storyboard',shots:[{description:'远景',duration:2,camera:''},{description:'近景',duration:3,camera:'推近'}]}},{id:'i',data:{kind:'image',assetId:'frame'}}];
    const refs=connectedReferences('v',nodes,[{id:'a',source:'s',target:'v'},{id:'b',source:'i',target:'v'}],'','');
    const result=canvasReferenceParams(refs,{duration:10},'v','video');
    expect(result.duration).toBe(5); expect(result.source_asset_ids).toEqual(['frame']);
    expect(refs[0].text.indexOf('远景')).toBeLessThan(refs[0].text.indexOf('近景'));
    expect(()=>canvasReferenceParams([...refs,refs[0]],{},'v','video')).toThrow('一份分镜');
  });
  it('blocks unfinished storyboard before submission',()=>{
    const refs=connectedReferences('v',[{id:'s',data:{editor:'storyboard',shots:[{description:'',duration:3}]}}],[{id:'e',source:'s',target:'v'}],'','');
    expect(()=>canvasReferenceParams(refs,{},'v','video')).toThrow('完善分镜');
  });
});

it('selects actual GPT Image 2.5 variant IDs without falling back to unrelated models', () => {
  expect(cutoutModel(['gpt-image-2', 'gpt-image-2.5-flare', 'gpt-image-2.5-sunburst'])).toBe('gpt-image-2.5-flare');
  expect(cutoutModel(['openai/gpt-image-2.5-sunburst-2026-10-01'])).toBe('openai/gpt-image-2.5-sunburst-2026-10-01');
  expect(cutoutModel(['gpt-image-2.5'])).toBe('gpt-image-2.5');
  expect(cutoutModel(['gpt-image-2', 'gpt-image-2.5-other'])).toBeUndefined();
});
