import { describe, expect, it } from 'vitest';
import { drawingPoint, copyDrawing } from './drawing';
import { canvasReferenceParams, connectedReferences } from './canvasReferences';

describe('layout drawing references', () => {
  it('maps zoomed mouse coordinates to stable image coordinates', () => {
    const drawing = {width:1024,height:768,strokes:[]};
    for (const scale of [.25, .7, 1, 2]) {
      const rect = {left:120,top:80,width:1024*scale,height:768*scale};
      expect(drawingPoint(120+512*scale,80+384*scale,rect,drawing)).toEqual([512,384]);
      expect(drawingPoint(0,0,rect,drawing)).toEqual([0,0]);
    }
    expect(copyDrawing({...drawing,revision:'ignored'} as any)).toEqual(drawing);
  });
  it('uses the latest saved PNG from a drawing edge and rejects a cleared board', () => {
    const nodes = [{id:'drawing',data:{kind:'image',editor:'drawing',assetId:'saved-2'}},{id:'target',data:{kind:'image'}}];
    const edges = [{id:'edge',source:'drawing',target:'target'}];
    const refs = connectedReferences('target',nodes,edges,'http://localhost','project');
    expect(canvasReferenceParams(refs,{},'target','image').source_asset_ids).toEqual(['saved-2']);
    nodes[0].data.assetId = undefined;
    expect(() => canvasReferenceParams(connectedReferences('target',nodes,edges,'','project'),{},'target','image')).toThrow('还没有内容');
  });
});
