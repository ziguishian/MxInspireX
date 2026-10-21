import {test} from 'vitest';
import assert from 'node:assert/strict';
import {boundedJson,mergeSessionInput,prepareModelInput,restoreCompletedHistory,ProjectSession} from '../app/sdk_context.mjs';

const user = text => ({type:'message',role:'user',content:[{type:'input_text',text}]});
test('one asset with different upload and memory previews is sent once without losing other images',()=>{
  const input=[{...user('只调整背景，产品不变'),content:[...user('只调整背景，产品不变').content,
    {type:'input_image',image:'data:image/jpeg;base64,YQ=='},{type:'input_image',image:'data:image/jpeg;base64,Yw=='}]}];
  const canonical=JSON.stringify(input);
  const view=prepareModelInput({input},{contextLength:128000,
    memory:{analyzed:true,attachments:[{assetId:'product',mime:'image/jpeg',data:'Yg==',sha256:'original'}]},
    attachmentPreviews:[{assetId:'product',mime:'image/jpeg',data:'YQ=='}]});
  assert.equal(view.manifest.inputImages,2);
  assert.ok(JSON.stringify(view.modelData.input).includes('只调整背景，产品不变'));
  assert.ok(!JSON.stringify(view.modelData.input).includes('base64,YQ=='));
  assert.ok(JSON.stringify(view.modelData.input).includes('base64,Yw=='));
  assert.equal(JSON.stringify(input),canonical);
});
test('a long current turn shrinks completed pairs while preserving current evidence, corrections and originals',()=>{
  const input=[user('保留原始 Logo，只修改背景，不改变质量')];
  for(let i=0;i<12;i++) input.push(
    {type:'function_call',callId:`c${i}`,name:'generate_image',arguments:JSON.stringify({prompt:'生成描述'.repeat(400),source_asset_id:'original'})},
    {type:'function_call_result',callId:`c${i}`,output:JSON.stringify({status:'succeeded',assetId:`asset-${i}`,node:{id:`node-${i}`},description:'已完成细节'.repeat(400)})});
  const rejection={status:'reference_mismatch',validation:{expectedAssetIds:['original'],details:'修正依据'.repeat(700)}};
  input.push({type:'function_call',callId:'bad',name:'image_edit',arguments:JSON.stringify({source_asset_id:'incorrect'})},
    {type:'function_call_result',callId:'bad',output:JSON.stringify(rejection)},
    {type:'function_call',callId:'latest',name:'asset_inspect',arguments:'{"asset_id":"original"}'},
    {type:'function_call_result',callId:'latest',output:JSON.stringify({assetId:'original',description:'当前必须保留的图像信息'})});
  const canonical=JSON.stringify(input);
  const view=prepareModelInput({input,instructions:'规则'},{contextLength:128000,toolSchemaChars:1200});
  assert.ok(view.manifest.receiptCount>=10);
  assert.ok(view.manifest.localAfterTokens<view.manifest.localBeforeTokens*.5);
  assert.equal(view.modelData.input[0].content[0].text,input[0].content[0].text);
  assert.ok(JSON.stringify(view.modelData.input).includes('asset-0'));
  assert.deepEqual(JSON.parse(view.modelData.input.find(i=>i.callId==='bad' && i.type==='function_call_result').output),rejection);
  assert.ok(JSON.stringify(view.modelData.input).includes('当前必须保留的图像信息'));
  assert.equal(JSON.stringify(input),canonical);
  const calls=view.modelData.input.filter(i=>i.type==='function_call').map(i=>i.callId);
  assert.deepEqual(calls,view.modelData.input.filter(i=>i.type==='function_call_result').map(i=>i.callId));
});
test('tool schema consumes capacity and an unchanged oversized required context is not reported as compacted',()=>{
  assert.throws(()=>prepareModelInput({input:[user('当前需求')],instructions:'完整规则'},{contextLength:8000,toolSchemaChars:4000}),/超出模型容量/);
  const view=prepareModelInput({input:[user('原始要求'.repeat(4000))]},{contextLength:128000});
  assert.equal(view.manifest.localCompacted,false);
  assert.equal(view.manifest.localBeforeTokens,view.manifest.localAfterTokens);
  assert.equal(view.manifest.localBudgetExceeded,true);
});
test('large fixed rules do not evict short recent original constraints under the soft budget',()=>{
  const input=[user('品牌必须蓝色，不改 Logo'),{type:'message',role:'assistant',content:[{type:'output_text',text:'收到，保留标识'}]},user('继续做杯子')];
  const view=prepareModelInput({input,instructions:'规则'.repeat(6500)},{contextLength:128000,toolSchemaChars:24000});
  assert.ok(JSON.stringify(view.modelData.input).includes('品牌必须蓝色，不改 Logo'));
  assert.ok(JSON.stringify(view.modelData.input).includes('收到，保留标识'));
  assert.ok(view.manifest.localBudgetExceeded);
});
test('text-only history does not replay Responses message IDs without their reasoning dependencies',()=>{
  const prior={type:'message',id:'msg_prior',role:'assistant',status:'completed',content:[{type:'output_text',text:'旧轮结论，保留原图'}]};
  const activeReasoning={type:'reasoning',id:'rs_active',content:[],providerData:{encrypted_content:'opaque-active'}};
  const activeCall={type:'function_call',id:'fc_active',callId:'active',name:'asset_inspect',arguments:'{"asset_id":"original"}'};
  const input=[user('原图不要改变'),{type:'reasoning',id:'rs_prior',content:[],providerData:{encrypted_content:'opaque-prior'}},prior,
    user('继续完成三张图'),activeReasoning,activeCall,{type:'function_call_result',callId:'active',output:'{"assetId":"original"}'}];
  const canonical=JSON.stringify(input);
  const view=prepareModelInput({input,instructions:'规则'.repeat(6500)},{api:'responses',contextLength:128000,toolSchemaChars:24000});
  assert.ok(!view.modelData.input.some(item=>item.id==='rs_prior'));
  const transcript=view.modelData.input.find(item=>item.role==='assistant');
  assert.deepEqual(transcript.content,prior.content);
  assert.equal(transcript.id,undefined);
  assert.deepEqual(view.modelData.input.find(item=>item.id==='rs_active'),activeReasoning);
  assert.deepEqual(view.modelData.input.find(item=>item.id==='fc_active'),activeCall);
  assert.equal(JSON.stringify(input),canonical);
});
test('session cache follows acknowledged transactions and invalidates after a lost response',async()=>{
  const originalFetch=globalThis.fetch;
  const requests=[];let items=[user('原始资料')],revision=0,fail=false;
  globalThis.fetch=async (_url,{body})=>{
    const data=JSON.parse(body);requests.push(data.action);
    if(data.action==='mutate') {
      assert.equal(data.revision,revision);
      if(data.transaction.type==='append_items')items.push(...data.transaction.items);
      revision++;
      if(fail) {fail=false;throw new Error('lost response');}
      return Response.json({sessionId:'project:p',revision});
    }
    return Response.json({sessionId:'project:p',revision,items:data.limit===0 ? [] : items});
  };
  try {
    const session=new ProjectSession({gateway:{baseUrl:'http://fixture.invalid',projectId:'p',taskId:'t'}});
    await session.acquire();
    await session.addItems([user('新增')]);
    for(let i=0;i<4;i++)assert.equal((await session.getItems()).length,2);
    const copy=await session.getItems();copy[0].content[0].text='outside mutation';
    assert.equal((await session.getItems())[0].content[0].text,'原始资料');
    assert.equal(requests.filter(x=>x==='get').length,0);
    fail=true;await assert.rejects(session.addItems([user('已提交但应答丢失')]),/lost response/);
    assert.equal((await session.getItems()).length,3);
    assert.equal(requests.filter(x=>x==='mutate').length,2,'no implicit replay');
    await session.release();
    await session.getItems();
    assert.equal(requests.filter(x=>x==='get').length,2);
  } finally {globalThis.fetch=originalFetch;}
});
test('derived brief remains separate from original request and sourced decisions during compaction',()=>{
  const original='船长28.8米，空高不超过4.5米，不要PPT';
  const frame={designState:{goal:original,decisions:{height:{value:'不超过4.5米',status:'confirmed',quote:'空高不超过4.5米'}},
    brief:{summary:'观光船概念设计',assumptions:['木色装饰'],openQuestions:['航区？'],sourceTaskId:'current',status:'derived'}}};
  for(const api of ['responses','chat_completions']) {
    const input=[user('旧历史'.repeat(12000)),user(original)];
    const result=prepareModelInput({input},{frame,api,contextLength:32000});
    assert.ok(JSON.stringify(result.modelData.input).includes('designBrief'));
    assert.ok(JSON.stringify(result.modelData.input).includes('derived'));
    assert.ok(JSON.stringify(result.modelData.input).includes('木色装饰'));
    assert.ok(JSON.stringify(result.modelData.input).includes('不超过4.5米'));
    assert.ok(result.modelData.input.some(item=>item.content?.[0]?.text===original));
  }
});
test('model handoff replays only completed history and preserves existing messages',async()=>{
  const stored=[user('请使用两张参考设计包装')];
  const call={type:'function_call',callId:'image-call',name:'generate_image',arguments:'{}'};
  const result={type:'function_call_result',callId:'image-call',output:'saved-asset'};
  const session={getItems:async()=>structuredClone(stored),addItems:async items=>stored.push(...items)};
  await assert.rejects(restoreCompletedHistory(session,[...stored,call],'pending'),/工具回执/);
  await assert.rejects(restoreCompletedHistory(session,[user('另一个任务'),call,result],'different'),/工具回执/);
  assert.equal(stored.length,1);
  const completed=[...stored,call,result];
  await restoreCompletedHistory(session,completed,'complete');
  await restoreCompletedHistory(session,completed,'complete');
  assert.deepEqual(stored,completed);
  stored.push(user('后续用户修改'));
  await assert.rejects(restoreCompletedHistory(session,completed,'stale'),/工具回执/);
  assert.equal(stored.length,4);
});
test('batch scope and real completed-node references survive ordinary history trimming',()=>{
  const frame={designBatch:{intent:'next_batch',status:'needs_plan',number:2,itemIds:[],suggestedNext:['第二批海报']},deliveryProgress:[{id:'B1',status:'passed',nodeIds:['original-node']}]};
  for(const api of ['responses','chat_completions']) {
    const result=prepareModelInput({input:[user('旧历史'.repeat(12000)),user('好的，继续')]},{frame,api,contextLength:32000});
    assert.ok(JSON.stringify(result.modelData.input).includes('needs_plan'));
    assert.ok(JSON.stringify(result.modelData.input).includes('original-node'));
    assert.ok(JSON.stringify(result.modelData.input).includes('第二批海报'));
  }
});
test('large HTML stays valid JSON with matching tool call/results and original history intact',()=>{
  const html = '<main>'+('带引号"和换行\n'.repeat(10000))+'</main>';
  const input=[user('保留蓝色品牌并修改刚才的网页'),{type:'function_call',name:'canvas_create_html',callId:'one',arguments:JSON.stringify({html,canvas_node_id:'node'})},
    {type:'function_call_result',callId:'one',name:'canvas_create_html',output:{type:'text',text:JSON.stringify({node:{id:'node',data:{html}}})}}];
  const result=prepareModelInput({instructions:'规则',input},{contextLength:32000});
  assert.equal(JSON.parse(result.modelData.input[1].arguments).canvas_node_id,'node');
  assert.equal(JSON.parse(result.modelData.input[2].output.text).node.id,'node');
  assert.equal(result.modelData.input[1].callId,result.modelData.input[2].callId);
  assert.equal(JSON.parse(input[1].arguments).html,html);
  assert.ok(result.manifest.inputChars<16000);
  assert.doesNotThrow(()=>JSON.parse(boundedJson({html},1000)));
});
test('recent referenced image survives when older duplicated image turn is removed',()=>{
  const picture={type:'input_image',image:'data:image/png;base64,YQ=='};
  const old=user('旧内容'.repeat(12000));old.content.push(picture);
  const current=user('修改这张图');current.content.push(picture);
  const result=prepareModelInput({input:[old,user('另一个历史'),current]},{contextLength:32000});
  assert.equal(result.manifest.inputImages,1);
  assert.ok(result.modelData.input.some(item=>item.content?.some(p=>p.type==='input_image' && p.image===picture.image)));
  assert.ok(result.manifest.omitted>0);
});
test('dynamic context keeps only the latest four raw user turns while retaining the current request',()=>{
  const input=Array.from({length:7},(_,index)=>user(`turn-${index}-`+'内容'.repeat(100)));
  const result=prepareModelInput({input},{contextLength:128000});
  const sent=JSON.stringify(result.modelData.input);
  assert.ok(!sent.includes('turn-0-') && !sent.includes('turn-1-') && !sent.includes('turn-2-'));
  for(const index of [3,4,5,6]) assert.ok(sent.includes(`turn-${index}-`));
  assert.ok(result.manifest.omitted>=3);
  assert.ok(result.manifest.localAfterTokens<=result.manifest.localBeforeTokens);
});
test('evidence and clock reach later stages with body types and stable IDs',()=>{
  const result=prepareModelInput({instructions:'规则',input:[user('汇总成网页')]},{contextLength:32000,frame:{clock:{reportAsOf:'2026-09-14'},scope:{nodeIds:['n']},evidence:[{id:'search',evidenceType:'search_summary',text:'摘要'}],handoff:{evidence:[{id:'body',evidenceType:'web_body',text:'75 起事件'}]}}});
  assert.ok(JSON.stringify(result.modelData.input).includes('75 起事件'));
  assert.deepEqual(result.manifest.evidenceIds,['search','body']);
  assert.deepEqual(result.manifest.nodeIds,['n']);
});
test('required current input is never silently discarded for model capacity',()=>{
  assert.throws(()=>prepareModelInput({input:[user('当前要求'.repeat(12000))]},{contextLength:8000}),/超出模型容量/);
  const latest=user('本轮');assert.deepEqual(mergeSessionInput([latest],[latest]),[latest]);
});
test('long earlier requirements cannot crowd evidence and current target out of the frame',()=>{
  const frame={clock:{reportAsOf:'2026-09-14'},requirements:{earlierUserExcerpts:Array.from({length:14},(_,i)=>({taskId:String(i),user:'历史约束'.repeat(200)}))},
    scope:{mode:'references',nodeIds:['report'],nodes:[{id:'report',data:{html:'<main>报告</main>'.repeat(3000)}}]},
    evidence:[{id:'body',evidenceType:'web_body',text:'已读取正文：75 起事件'}]};
  const result=prepareModelInput({input:[user('将研究做成网页')],instructions:'约束'},{frame});
  assert.ok(JSON.stringify(result.modelData.input).includes('75 起事件'));
  assert.deepEqual(result.manifest.evidenceIds,['body']);assert.deepEqual(result.manifest.nodeIds,['report']);
});

test('selected memory and original reference survive trimming, deduplication and both transports', async()=>{
  const {createHash}=await import('node:crypto');
  const original='data:image/png;base64,YQ==',preview='data:image/jpeg;base64,Yg==';
  const memory={memoryRevision:7,selected:[{id:'brand',version:2,content:'本轮颜色为蓝色，原 Logo 为参考'}],referenceSnapshots:[{id:'ref7',references:[{assetId:'logo',role:'logo'}]}],
    attachments:[{assetId:'logo',sha256:createHash('sha256').update('a').digest('hex'),mime:'image/jpeg',data:'Yg==',role:'logo',purpose:'原标识'}]};
  const old=user('历史'.repeat(18000));old.content.push({type:'input_image',image:original});
  const current=user('继续做水杯');current.content.push({type:'input_image',image:original});
  for(const api of ['responses','chat_completions']) {
    const result=prepareModelInput({input:[old,current]},{memory,contextLength:32000,api});
    assert.equal(result.manifest.inputImages,1);
    assert.equal(result.modelData.input.at(-1).content.at(-1).image,preview);
    assert.ok(JSON.stringify(result.modelData.input).includes('本轮颜色为蓝色'));
    assert.equal(result.manifest.memoryRevision,7);
    assert.ok(result.manifest.omitted>0);
    assert.equal(current.content.length,2,'canonical evidence is unchanged');
  }
});
test('memory updates hide superseded values in request receipts while retaining the audit record',()=>{
  const input=[user('这次用绿色'),{type:'function_call',name:'conversation_memory_update',callId:'m',arguments:JSON.stringify({changes:[{content:'旧蓝色'}]})},
    {type:'function_call_result',callId:'m',output:JSON.stringify({status:'recorded',revision:2,state:{selected:[{id:'color',content:'旧蓝色'}]}})}];
  const result=prepareModelInput({input},{memory:{selected:[{id:'color',content:'绿色'}]},contextLength:32000});
  assert.ok(!JSON.stringify(result.modelData.input).includes('旧蓝色'));
  assert.ok(JSON.stringify(input).includes('旧蓝色'));
  assert.equal(result.modelData.input[1].callId,result.modelData.input[2].callId);
});
test('an omitted history image cannot exhaust the remaining capacity',()=>{
  const input=Array.from({length:25},(_,i)=>({type:'message',role:'user',content:[{type:'input_text',text:'old'.repeat(8000)},{type:'input_image',image:`data:image/png;base64,${Buffer.from(String(i)).toString('base64')}`}]}));
  const result=prepareModelInput({input:[...input,user('继续')]},{contextLength:32000});
  assert.equal(result.manifest.inputImages,0);
});

test('object-shaped memory receipts are summarized without changing canonical evidence',()=>{
  const record={type:'function_call_result',callId:'m',output:{type:'text',text:JSON.stringify({status:'recorded',revision:1,state:{selected:[{id:'color',content:'已过期的颜色'}]}})}};
  const input=[user('更新颜色'),{type:'function_call',name:'conversation_memory_update',callId:'m',arguments:'{}'},record];
  const result=prepareModelInput({input},{memory:{selected:[{id:'color',content:'绿色'}]},contextLength:32000});
  assert.ok(!JSON.stringify(result.modelData.input).includes('已过期的颜色'));
  assert.ok(record.output.text.includes('已过期的颜色'));
});

test('rejected memory updates retain the failed arguments and field-specific correction evidence',()=>{
  const failure={status:'memory_invalid',revision:2,instruction:'请从用户原文选取',validation:{key:'logo',field:'source.quote',sourceEvidence:{taskId:'t',userText:'用这个logo做一套视觉'}}};
  for(const output of [JSON.stringify(failure),{type:'text',text:JSON.stringify(failure)},[{type:'text',text:JSON.stringify(failure)}]]) {
    const args=JSON.stringify({changes:[{key:'logo',source:{quote:'图片附件 @1：logo.png'}}]});
    const input=[user('继续'),{type:'function_call',name:'conversation_memory_update',callId:'bad',arguments:args},
      {type:'function_call_result',callId:'bad',output}];
    const result=prepareModelInput({input},{contextLength:32000});
    assert.equal(result.modelData.input[1].arguments,args);
    assert.ok(JSON.stringify(result.modelData.input).includes('用这个logo做一套视觉'));
    assert.ok(JSON.stringify(result.modelData.input).includes('source.quote'));
  }
});
