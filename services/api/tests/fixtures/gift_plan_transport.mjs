import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {readFileSync} from 'node:fs';
import {sessionResponse} from './session_transport.mjs';

const mode = process.env.FIXTURE_GIFT_MODE;
const plan = JSON.parse(process.env.FIXTURE_GIFT_PLAN);
let round = 0;
const generated = [];
const lookups = new Map();
const operations = new Map();
function reply(api, operation, content = '七项礼盒设计已保存。') {
  const id = `${mode}-${round}`;
  const args = operation?.raw ?? JSON.stringify(operation?.args);
  if (api === 'responses') {
    const item = operation ? {type:'function_call',id:'fc-'+id,call_id:id,name:operation.name,arguments:args,status:'completed'}
      : {type:'message',id:'msg-'+id,role:'assistant',status:'completed',content:[{type:'output_text',text:content,annotations:[]}]};
    const response = {id:'res-'+id,object:'response',model:'fixture',status:'completed',output:[item],usage:{input_tokens:20,output_tokens:10,total_tokens:30}};
    const events = [{type:'response.created',response:{...response,status:'in_progress',output:[]}},
      {type:'response.output_item.added',output_index:0,item},{type:'response.output_item.done',output_index:0,item},{type:'response.completed',response}];
    return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
  }
  const chunk = (delta,finish_reason=null)=>'data: '+JSON.stringify({id,object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta,finish_reason}]})+'\n\n';
  const delta = operation ? {role:'assistant',tool_calls:[{index:0,id,type:'function',function:{name:operation.name,arguments:args}}]} : {role:'assistant',content};
  return new Response(chunk(delta)+chunk({},operation?'tool_calls':'stop')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
}
globalThis.fetch = async(input, options={}) => {
  const url = String(typeof input==='string' ? input : input.url);
  if (mode === 'upload_failed' && url.endsWith('/agent-tools/generate_image')) {
    return Response.json({detail:'参考图上传失败，尚未提交生成请求',errorCode:'reference_upload_failed',stopTool:true,retryable:false},{status:422});
  }
  if (mode === 'design_spec_stalled' && url.endsWith('/agent-tools/generate_image')) {
    return Response.json({tool:'generate_image',status:'design_spec_required',submitted:false,
      instruction:`缺少 visualDirection，修正计划后再生成（${round}）`});
  }
  const session = sessionResponse(url, options); if (session) return session;
  if(url.includes('/image-operations/')) {
    assert.equal(options.method,'GET');
    const operation=operations.get(url.split('/').at(-1));
    assert.ok(operation,'poll only the accepted operation');
    operation.polls++;
    return Response.json(operation.polls===1 ? {state:'running',operationId:operation.id}
      : {state:'completed',operationId:operation.id,output:operation.output,httpStatus:operation.httpStatus});
  }
  const body = JSON.parse(options.body || await input.text());
  if (url.includes('/agent-tools/') || url.endsWith('/tool-result')) {
    const lookup=url.endsWith('/tool-result');
    if(lookup){
      if(mode==='durable') {
        const operation=[...operations.values()].find(op=>JSON.stringify(op.args)===JSON.stringify(body.arguments));
        assert.ok(operation,'a lost submit reply must look up the original request');
        operation.polls++;
        return Response.json(operation.polls===1 ? {state:'running',operationId:operation.id}
          : {state:'completed',operationId:operation.id,output:operation.output,httpStatus:operation.httpStatus});
      }
      const key=JSON.stringify(body.arguments);
      const count=(lookups.get(key)||0)+1;lookups.set(key,count);
      if(count===1)return Response.json({state:'running'});
    }
    if(['partial_late','durable_partial'].includes(mode) && url.endsWith('/generate_image') && body.deliverable_ids?.[0]==='gift-tea'){
      // Each fixture gateway runs in its own process. Let the other independent
      // calls finish before recording the one unknown receipt (production uses
      // concurrent threads and live receipt scopes in a single sidecar).
      for(let i=0;generated.length<6 && i<100;i++)await new Promise(resolve=>setTimeout(resolve,10));
      assert.equal(generated.length,6);
    }
    const result = spawnSync(process.env.FIXTURE_PYTHON,[fileURLToPath(new URL('./memory_tool_fixture.py',import.meta.url))],{
      input:JSON.stringify({name:lookup?'fixture_receipt':decodeURIComponent(url.split('/').at(-1)),projectId:process.env.FIXTURE_PROJECT,
        taskId:lookup?url.split('/').at(-2):options.headers['x-aics-task-id'],callId:options.headers['x-aics-tool-call-id'],role:options.headers['x-aics-agent-role'],arguments:lookup?body.arguments:body}),encoding:'utf8',env:process.env});
    assert.equal(result.status,0,result.stderr);
    const response=JSON.parse(result.stdout);
    if(url.endsWith('/generate_image') && response.body.assetId) generated.push({assetId:response.body.assetId,nodeId:response.body.node.id,itemId:body.deliverable_ids[0]});
    if(mode==='durable' && url.endsWith('/generate_image')) {
      assert.equal(options.headers['x-aics-async-tool'],'1');
      const id=body.deliverable_ids[0];
      assert.ok(!operations.has(id),'generation must only be submitted once');
      operations.set(id,{id,args:body,output:response.body,httpStatus:response.status,polls:0});
      if(id==='gift-box')throw new TypeError('fetch failed: lost accepted reply');
      return Response.json({operationId:id,state:'running'},{status:202});
    }
    if(['partial_late','durable_partial'].includes(mode) && url.endsWith('/generate_image') && ['gift-box','gift-silk'].includes(body.deliverable_ids?.[0]))throw new TypeError('fetch failed: UND_ERR_HEADERS_TIMEOUT');
    return Response.json(response.body,{status:response.status});
  }
  assert.match(url,/^http:\/\/gift-fixture.invalid\/v1\/(responses|chat\/completions)$/,'No live/paid traffic');
  const index=round++, api=url.endsWith('/responses')?'responses':'chat_completions', text=JSON.stringify(body);
  if(mode.startsWith('durable')) {
    const partial=mode==='durable_partial';
    const batchRound=partial?0:2;
    assert.ok(index<=batchRound+1,'completion must hand off directly to necessary review');
    if(index<=batchRound) {
      for(const name of (index===batchRound ? ['design_state','design_plan','generate_image','generate_batch'] : ['design_state','design_plan'])) {
        const tool=body.tools.find(t=>(t.name || t.function?.name)===name);
        const definition=tool.function || tool;
        assert.equal(definition.strict,true,name+' must use the verified strict endpoint');
        assert.equal(definition.parameters.additionalProperties,false);
      }
    }
    if(!partial && index<batchRound)assert.ok(!body.tools.some(t=>(t.name || t.function?.name)==='generate_batch'),'planning gate excludes premature generation');
    if(!partial && index===0)return reply(api,{name:'design_state',args:{brief:{summary:plan.goal,assumptions:[],openQuestions:[],visualDirection:plan.visualDirection},decisions:null}});
    if(!partial && index===1){const planned=structuredClone(plan);planned.visualDirection=null;return reply(api,{name:'design_plan',args:{plan:planned,change_reason:null,expected_revision:null,expected_scope_id:null}});}
    if(index===batchRound)return reply(api,{name:'generate_batch',args:{items:plan.deliverables.map(d=>({tool:'generate_image',deliverable_ids:[d.id],arguments:{prompt:d.title,params:{size:'1024x1024',quality:null},model:null,quality:null,source_asset_id:null,production_notes:null}}))}});
    assert.equal((body.tools||[]).length,0);
    assert.equal(generated.length,partial?6:7);
    if(!partial)assert.ok(operations.size===7 && [...operations.values()].every(op=>op.polls===2),'all seven receipts recovered without another submit');
    for(const item of generated)assert.ok(text.includes(item.assetId));
    return reply(api,null,JSON.stringify({passed:true,summary:'已保存图像完成总览审查',checks:generated.map(item=>({category:'content',status:'passed',artifactId:item.nodeId,planItemId:item.itemId,message:'对应礼品主体与材料可辨'}))}));
  }
  if(mode==='partial_late'){
    assert.ok(index<3,'no-op ready plan must hand off to review without extra model rounds');
    if(index===0)return reply(api,{name:'generate_batch',args:{items:plan.deliverables.map(d=>({tool:'generate_image',arguments:{prompt:d.title,provider:'local-placeholder',output_mode:'create',quality:'draft',size:'1024x1024',deliverable_ids:[d.id]}}))}});
    if(index===1){
      assert.equal(generated.length,6);assert.equal(lookups.size,2);assert.ok([...lookups.values()].every(n=>n===2));
      assert.ok(text.includes('generation_unconfirmed'));
      for(const item of generated)assert.ok(text.includes(item.assetId),'late results must reach the Agent');
      return reply(api,{name:'design_plan',args:{plan:{...plan,goal:'重新描述已经完成的本轮计划'}}});
    }
    assert.equal((body.tools||[]).length,0,'necessary overview review still runs');
    for(const item of generated)assert.ok(text.includes(item.assetId),'review includes all six saved images');
    return reply(api,null,JSON.stringify({passed:true,summary:'六张已保存图像完成总览审查；陶罐生成结果仍待核对',checks:generated.map(item=>({category:'content',status:'passed',artifactId:item.nodeId,planItemId:item.itemId,message:'对应礼品主体与材料可辨'}))}));
  }
  if (mode==='recorded_failure') {
    const recorded=JSON.parse(readFileSync(new URL('./gift_failed_call_shapes.json',import.meta.url),'utf8'));
    assert.ok(index<6,'the recorded failure must finish with one final review');
    const allowance=api==='responses'?body.max_output_tokens:(body.max_completion_tokens || body.max_tokens);
    if(index===0) {
      assert.equal(allowance,32768);
      const definition=body.tools.find(t=>(t.name || t.function?.name)==='design_plan');
      const schema=definition.parameters || definition.function.parameters;
      assert.deepEqual(schema.properties.plan.properties.coverage.items.properties.area.enum,['objectives','concept','system','visuals','delivery']);
      return reply(api,{name:'design_plan',args:recorded.unmappedPlan});
    }
    if(index===1) { assert.ok(text.includes('plan.coverage.*.area')); return reply(api,{name:'design_plan',args:recorded.labeledPlan}); }
    if(index===2) { assert.ok(text.includes('ready')); return reply(api,{name:'design_plan',args:recorded.misnestedPlan}); }
    if(index===3) { assert.ok(text.includes('plan_reused')); return reply(api,{name:'generate_batch',args:recorded.batch}); }
    if(index===4)return reply(api,null);
    assert.equal(allowance,2000);
    assert.equal((body.tools || []).length,0);
    assert.equal(generated.length,7);
    const master=generated.find(item=>item.itemId==='gift_outer');
    // Mock the necessary visual comparison using actual generated fixture IDs;
    // the production review must still reject a generic pass without evidence.
    const checks=generated.filter(item=>item!==master).map(item=>{
      assert.ok(text.includes(item.nodeId) && text.includes(item.assetId) && text.includes(master.assetId));
      return {category:'layout',status:'passed',seriesId:'gift_suite',planItemId:item.itemId,artifactId:item.nodeId,evidenceIds:[master.assetId,item.assetId],message:'材质可辨，配色与光线一致'};
    });
    return reply(api,null,JSON.stringify({passed:true,summary:'七项齐全，主题和配色一致',checks}));
  }
  if (mode==='long_plan') {
    assert.ok(index<5,'one plan, one batch, one review; no repeated planning');
    const allowance=api==='responses'?body.max_output_tokens:(body.max_completion_tokens || body.max_tokens);
    if(index===0) return reply(api,{name:'design_state',args:{brief:{summary:plan.goal,assumptions:[],openQuestions:[],visualDirection:plan.visualDirection}}});
    if(index===1) {
      // A realistic detailed plan exceeds the old 4096-token response cap.
      // Enforce the server boundary in the transport; don't execute partial JSON.
      assert.ok(allowance>=32768,'a seven-item detailed plan must fit before its first submission');
      assert.ok(text.includes('省略重复的 visualDirection'),'reuse saved judgement instead of serializing it again');
      const detailed=structuredClone(plan);delete detailed.visualDirection;
      for(const d of detailed.deliverables) {
        d.imageSpec.materialConstruction=('明确'+d.title+'的层叠结构、接缝处理、表面肌理与材料厚薄关系；材质各有区分，不以装饰图形掩盖结构。').repeat(3);
        d.imageSpec.lightSurface='用柔和侧光呈现真实材质差异，控制高光面积与阴影软硬，纸纤维清楚而不粗糙，釉面和漆面反射克制。';
      }
      return reply(api,{name:'design_plan',args:{plan:detailed}});
    }
    if(index===4)assert.equal(allowance,2000,'overview review keeps its separate limit');
  }
  if (mode === 'upload_failed') {
    assert.ok(index < 2, 'failed upload must stop without another model or generation request');
    if (index === 0) return reply(api,{name:'design_plan',args:{plan:{...plan,deliverables:plan.deliverables.slice(0,1)}}});
    return reply(api,{name:'generate_image',args:{prompt:'礼盒外盒',deliverable_ids:['gift-box'],provider:'local-placeholder'}});
  }
  if (mode === 'prerequisite_recovery') {
    assert.ok(index < 5, 'prerequisite repair must reach generation');
    if (index === 0 || index === 3) {
      const draft = structuredClone(plan); delete draft.visualDirection;
      return reply(api,{name:'design_plan',args:{plan:draft}});
    }
    if (index === 1) return reply(api,{name:'design_state',args:{brief:{summary:plan.goal,assumptions:[],openQuestions:[],visualDirection:plan.visualDirection}}});
    if (index === 2) return reply(api,{name:'report_progress',args:{summary:'已补齐视觉方向，继续原交付清单。'}});
    return reply(api,{name:'generate_batch',args:{items:plan.deliverables.map(d=>({tool:'generate_image',arguments:{prompt:d.title,provider:'local-placeholder',output_mode:'create',deliverable_ids:[d.id]}}))}});
  }
  if (mode === 'design_spec_stalled') {
    assert.ok(index < 3, 'design specification failures must stop after two corrections');
    return reply(api, {name:'generate_image',args:{prompt:'同一张海报',params:{aspect_ratio:'3:4'}}});
  }
  if (['schema_stalled','json_stalled','plan_stalled'].includes(mode)) {
    assert.ok(index<3,'stop before a fourth model call; two corrections only');
    if (index) assert.match(text,/invalid_arguments|plan_reused/);
    if (mode==='json_stalled') return reply(api,{name:'design_plan',raw:'not valid JSON'});
    const bad={...plan}; if(mode==='schema_stalled') delete bad.research;
    return reply(api,{name:'design_plan',args:{plan:bad}});
  }
  if (mode==='envelope') {
    assert.ok(index<5);
    if(index===0) {const copy={...plan};delete copy.research;return reply(api,{name:'design_plan',args:{plan:copy,research:plan.research}});}
    if(index===1)return reply(api,{name:'design_plan',args:{plan:{}}});
  } else if(mode!=='long_plan') {
    assert.ok(text.includes('gift-box') && text.includes('gift-silk'),'seven-item plan is injected on continuation');
    if(index===0)return reply(api,{name:'design_plan',args:{plan:{...plan,goal:'只是重新措辞，不改变七项设计'}}});
    if(index===1) {
      assert.ok(text.includes('plan_reused'));
      return reply(api,{name:'generate_batch',args:{items:plan.deliverables.map(d=>({tool:'unknown_generator',arguments:{prompt:d.title},deliverable_ids:[d.id]}))}});
    }
  }
  if(index===2) {
    if(!['envelope','long_plan'].includes(mode)) assert.ok(text.includes('invalid_arguments') && text.includes('items.*.tool'));
    return reply(api,{name:'generate_batch',args:{items:plan.deliverables.map(d=>({tool:'generate_image',deliverable_ids:[d.id],arguments:{
      prompt:`${d.title}；和光同尘赴自在；秋桂意象，创意六色；${d.imageSpec.materialConstruction}；${d.imageSpec.compositionFraming}`,
      provider:'local-placeholder',output_mode:'create',quality:'draft',size:'1024x1024'}}))}});
  }
  if(index===3)return reply(api,null);
  assert.equal(index,4,'one final overview review');
  assert.equal((body.tools || []).length,0,'review cannot regenerate');
  return reply(api,null,JSON.stringify({passed:true,summary:'七项齐全，主题和配色一致',checks:[]}));
};
