import {describe,it,expect} from 'vitest';
import {waitForImageResult} from '../app/image_result_wait.mjs';

describe('read-only late image receipt recovery',()=>{
  const base={baseUrl:'http://fixture.invalid',projectId:'project',taskId:'task',args:{prompt:'礼盒',deliverable_ids:['box']}};
  it('observes only the original audio operation',async()=>{
    const result=await waitForImageResult({...base,toolName:'generate_audio',operationId:'audio-original',fetchResult:async(url,request)=>{
      expect(url).toMatch(/audio-operations\/audio-original$/);expect(request.method).toBe('GET');
      return Response.json({state:'unconfirmed'});
    }});
    expect(result).toMatchObject({tool:'generate_audio',status:'generation_unconfirmed',retryable:false});
  });
  it('waits for the original active receipt, including a transient lookup failure',async()=>{
    const calls=[];let clock=0;
    const output={status:'succeeded',assetId:'saved',node:{id:'original'}};
    const result=await waitForImageResult({...base,now:()=>clock,sleep:async ms=>{clock+=ms;},fetchResult:async(url,request)=>{
      calls.push({url,request});
      if(calls.length===1)throw new TypeError('lookup disconnected');
      return Response.json(calls.length===2?{state:'running'}:{state:'completed',output});
    }});
    expect(result).toEqual(output);
    expect(calls).toHaveLength(3);
    for(const {url,request} of calls){
      expect(url).toBe('http://fixture.invalid/api/projects/project/tasks/task/tool-result');
      expect(JSON.parse(request.body)).toEqual({name:'generate_image',arguments:base.args});
    }
  });
  it.each(['unconfirmed','missing','rejected','cancelled'])('never resubmits a %s request',async state=>{
    let calls=0;
    const result=await waitForImageResult({...base,fetchResult:async()=>{calls++;return Response.json({state});}});
    expect(calls).toBe(1);
    expect(result.retryable).toBe(false);
    expect(result.status).toBe(state==='cancelled'?'cancelled':'generation_unconfirmed');
  });
  it('bounds waiting without treating unknown billing as a retryable failure',async()=>{
    let clock=0,calls=0;
    const result=await waitForImageResult({...base,timeoutMs:5,intervalMs:2,now:()=>clock,sleep:async ms=>{clock+=ms;},
      fetchResult:async()=>{calls++;return Response.json({state:'running'});}});
    expect(clock).toBe(5);expect(calls).toBe(3);
    expect(result).toMatchObject({status:'generation_unconfirmed',billingCertainty:'unknown',retryable:false});
  });
  it('polls a durable operation with GET and preserves local rejection status',async()=>{
    let clock=0;const calls=[];
    const result=await waitForImageResult({...base,operationId:'stable-operation',returnEnvelope:true,
      now:()=>clock,sleep:async ms=>{clock+=ms},fetchResult:async(url,request)=>{
        calls.push({url,request});
        return Response.json(calls.length===1 ? {state:'running'} : {state:'completed',httpStatus:422,output:{detail:'source_asset_id 不属于当前项目'}});
      }});
    expect(result).toEqual({httpStatus:422,output:{detail:'source_asset_id 不属于当前项目'}});
    expect(calls).toHaveLength(2);
    expect(calls.every(c=>c.url.endsWith('/image-operations/stable-operation') && c.request.method==='GET' && !c.request.body)).toBe(true);
  });
});
