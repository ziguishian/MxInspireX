import { describe, expect, it } from 'vitest';
import { generationBatchRequired, readyGenerationItems } from '../app/generation_batch.mjs';

const delivery = () => ({designPlan:{visualSeries:[{id:'roles',masterId:'a',memberIds:['a','b','c'],size:'1024x1536'}]},
  deliverables:['a','b','c'].map(id=>({id,title:id,nodeIds:[id],status:'ready'})),
  artifacts:['a','b','c'].map(id=>({nodeId:id,assetId:'asset-'+id,kind:'image',ready:true,imageInfo:{width:1024,height:1536},
    ...(id!=='a'?{visualSeries:{id:'roles',masterAssetId:'asset-a'}}:{})}))});
describe('visual series',()=>{
  it('runs one real master before the parallel variants',()=>{
    const constraints={designPlan:{scopeId:'scope',ready:true,deliverables:['a','b','c'].map(id=>({id,kind:'image',dependsOn:id==='a'?[]:['a']}))}};
    expect(readyGenerationItems(constraints).map(d=>d.id)).toEqual(['a']);
    const output={name:'generate_image',output:{status:'succeeded',node:{id:'a',data:{deliveryBinding:{scopeId:'scope',itemIds:['a']}}}}};
    expect(readyGenerationItems(constraints,[output]).map(d=>d.id)).toEqual(['b','c']);
    expect(generationBatchRequired([{tool:'generate_image',arguments:{deliverable_ids:['b']}}],constraints,[output]).readyDeliverables.map(d=>d.id)).toEqual(['b','c']);
  });
});

describe('consistency does not dictate scheduling',()=>{
  it('allows parallel members with shared constraints without a quality-review dependency',()=>{
    const report=delivery();delete report.designPlan.visualSeries[0].masterId;
    report.designPlan.deliverables=['a','b','c'].map(id=>({id,kind:'image',dependsOn:[],inputs:[]}));
    report.designPlan.ready=true;report.designPlan.scopeId='scope';
    for(const artifact of report.artifacts)delete artifact.visualSeries;
    expect(readyGenerationItems({designPlan:report.designPlan}).map(d=>d.id)).toEqual(['a','b','c']);
  });

});
