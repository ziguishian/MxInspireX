import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {sessionResponse} from './session_transport.mjs';

let round = 0, nodeId, imageCalls = 0, productAsset;
const nodeIds = new Set();
const kind = process.env.FIXTURE_KIND;
const mode = process.env.FIXTURE_MODE;
const inventoryMode = ['planned','plan_creation','access_rejected','selection_planned'].includes(mode);
globalThis.fetch = async (input, options={}) => {
  const url = typeof input === 'string' ? input : input.url;
  if (mode==='steering' && /\/updates(?:\/acknowledge)?$/.test(url)) return Response.json(round ? [{id:'supplement',text:'保留图像，补充一句使用建议',revision:1}] : []);
  const session = sessionResponse(url,options); if (session) return session;
  const body = JSON.parse(options.body || await input.text());
  if (url.includes('/agent-tools/')) {
    if (process.env.FIXTURE_ACCESS_FAILURE && url.endsWith('/generate_image')) {
      assert.equal(++imageCalls, 1, 'Access rejection must not cause a second image request');
      return Response.json({detail:'图像服务余额不足', errorCode:'image_provider_access', stopTool:true, retryable:false}, {status:422});
    }
    if (mode==='reference' && url.endsWith('/generate_image')) return Response.json({
      tool:'generate_image',status:'reference_selection_required',
      referenceSelection:{id:'reference-card',status:'pending',items:[],intro:'选择参考后继续'},
    });
    const result = spawnSync(process.env.FIXTURE_PYTHON,[fileURLToPath(new URL('./memory_tool_fixture.py',import.meta.url))],{
      input:JSON.stringify({name:url.split('/').at(-1),projectId:process.env.FIXTURE_PROJECT,taskId:options.headers['x-aics-task-id'],
        callId:options.headers['x-aics-tool-call-id'],role:options.headers['x-aics-agent-role'],arguments:body,
        fixtureAfterReview:false}),encoding:'utf8',env:process.env});
    assert.equal(result.status,0,result.stderr);
    const output=JSON.parse(result.stdout);
    if (mode==='product_identity' && url.endsWith('/generate_image') && output.body.status==='succeeded') {
      imageCalls++;
      if (body.deliverable_ids.includes('photo')) productAsset=output.body.assetId;
      else assert.equal(imageCalls,2,'Only one main image and one dependent scene may be generated');
    }
    if (output.body.node) {nodeId=output.body.node.id; nodeIds.add(nodeId);}
    return Response.json(output.body,{status:output.status});
  }
  assert.match(url,/^http:\/\/efficiency.invalid\/v1\/(responses|chat\/completions)$/);
  const api = url.endsWith('/responses'), index=round++;
  assert.ok(index<(['product_identity','packaging'].includes(mode)?3:['steering','plan_creation','image_input','image_multi','selection_planned'].includes(mode)?2:1),'No reviewer, extra wrap-up or nested text model may be called');
  const tools=(body.tools||[]).map(t=>t.function||t);
  let operation, text;
  if (mode==='packaging') {
    if (index===0) operation={name:'generate_image',args:{prompt:'产品包装概念'}};
    else if (index===1) {
      assert.ok(JSON.stringify(body).includes('planning_required'));
      operation={name:'design_plan',args:{plan:JSON.parse(process.env.FIXTURE_PLAN)}};
    } else operation={name:'generate_image',args:{prompt:'产品包装概念',deliverable_ids:['poster']}};
  } else if (mode==='product_identity') {
    if (index===0) operation={name:'design_plan',args:{plan:JSON.parse(process.env.FIXTURE_PLAN)}};
    else if (index===1) operation={name:'generate_batch',args:{items:[
      {tool:'generate_image',arguments:{prompt:'陶土香薰炉，白底产品摄影',deliverable_ids:['photo']}},
      {tool:'generate_image',arguments:{prompt:'同款香薰炉的窗边场景',deliverable_ids:['scene']}},
      {tool:'canvas_create_text',arguments:{text:'香薰炉，日常的小小陪伴。',deliverable_ids:['copy']}},
    ]}};
    else {
      assert.equal(imageCalls,1,'A scene must not run before the model receives the actual first image');
      assert.ok(productAsset);
      const json=JSON.stringify(body);
      assert.ok(json.includes(productAsset) && /data:image\//.test(json),'The next Agent turn must receive real image pixels and their asset binding');
      assert.ok(json.includes('awaiting_identity_source'));
      operation={name:'generate_image',args:{prompt:'同一陶土炉摆放在窗边木桌，柔和侧光',deliverable_ids:['scene'],reference_analysis:{
        images:[{asset_id:productAsset,mode:'inspiration',visual_prompt:'圆形陶土炉，拱形开口和顶部圆碟',use:'同一产品放到窗边木桌',preserve:'产品轮廓、结构、材质和颜色'}],
        synthesis:'产品造型不变，换成窗边生活场景'}}};
    }
  } else if (mode==='selection_planned' && index===0) {
    assert.ok(!tools.some(t=>t.name.startsWith('generate_') || ['generation_reference_check','canvas_create_text','canvas_create_html','canvas_create_media','canvas_update_node'].includes(t.name)),'Select before planned image/text writes');
    assert.ok(tools.some(t=>t.name==='conversation_memory_update'));
    operation={name:'conversation_memory_update',args:{expected_revision:Number(process.env.FIXTURE_MEMORY_REVISION),selected_ids:[]}};
  } else if (['image_input','image_local','image_edit','image_multi'].includes(mode)) {
    assert.ok(!tools.some(t=>['design_state','design_plan','generate_batch','generation_reference_check'].includes(t.name)));
    assert.ok(tools.length<=14,'Only the focused image tool set is advertised');
    const asset = process.env.FIXTURE_REFERENCE;
    const refs = [asset,...(process.env.FIXTURE_SECOND_REFERENCE ? [process.env.FIXTURE_SECOND_REFERENCE] : [])];
    if (index===0 && ['image_input','image_multi'].includes(mode)) {
      assert.ok(!tools.some(t=>t.name==='generate_image'),'Select references before a paid generation attempt');
      operation={name:'conversation_memory_update',args:{expected_revision:Number(process.env.FIXTURE_MEMORY_REVISION),selected_ids:refs.map(id=>'asset:'+id)}};
    } else {
      assert.ok(tools.some(t=>t.name==='generate_image'));
      operation={name:'generate_image',args:{prompt:mode==='image_edit' ? '图像编辑任务：将背景改成米色，保持蓝色主体不变。' : '蓝色陶瓷产品置于浅色桌面，柔和侧光。',source_asset_ids:refs,reference_analysis:{
        images:refs.map(id=>({asset_id:id,mode:mode==='image_edit'?'edit':'identity',visual_prompt:'蓝色产品',use:'保留产品身份',preserve:'产品形状与颜色'})),synthesis:'产品保持不变，更换浅色场景。'}}};
    }
  } else if (mode==='plan_creation' && index===0) {
    const planTool=tools.find(t=>t.name==='design_plan');
    assert.ok(planTool);
    assert.ok(!planTool.parameters.properties.expected_revision,'Revision is owned by the runtime');
    operation={name:'design_plan',args:{plan:JSON.parse(process.env.FIXTURE_PLAN),expected_revision:2,expected_scope_id:'state-revision-is-not-a-plan'}};
  } else if (index===0 || ['plan_creation','selection_planned'].includes(mode) && index===1) {
    assert.ok(!tools.some(t=>t.name==='generate_text'));
    if (!['clarification','packaging'].includes(mode)) assert.ok(!tools.some(t=>(inventoryMode ? ['design_plan','design_state','report_progress','generation_reference_check'] : ['design_plan','design_state','generation_reference_check']).includes(t.name)));
    operation = kind==='image' ? {name:'generate_image',args:{prompt:'简约蓝色海报'}}
      : kind==='text' ? {name:'canvas_create_text',args:{text:'完整的品牌设计文案。'}}
      : {name:'canvas_create_html',args:{html:'<!doctype html><html><head><meta name="viewport" content="width=device-width"></head><body><h1>设计作品</h1></body></html>'}};
    if (inventoryMode) operation={name:'generate_batch',args:{items:[
      {tool:'generate_image',arguments:{prompt:'简约蓝色海报',deliverable_ids:['poster']}},
      {tool:'canvas_create_text',arguments:{text:'本轮一张海报及应用清单。',title:'应用清单',deliverable_ids:['list'],application_items:[
        {title:'主海报',detail:'概念讨论',priority:'recommended',deliverable_id:'poster'},
        {title:'社交封面',detail:'后续适配',priority:'recommended'},
        {title:'活动横幅',detail:'参加活动时选配',priority:'optional'},
      ]}},
    ]}};
  } else if (mode==='steering' && index===1) {
    assert.ok(tools.length>0,'Steering must reach the main Agent before completion');
    assert.ok(tools.some(t=>t.name==='design_plan'),'Steering restores planning for changed scope');
    assert.ok(JSON.stringify(body).includes('补充一句使用建议'));
    text='作品已保存，可用于品牌概念讨论。';
  } else throw new Error('Unexpected extra model call');
  const id='efficiency-'+index;
  if (api) {
    const item=operation ? {type:'function_call',id:'fc-'+id,call_id:id,name:operation.name,arguments:JSON.stringify(operation.args),status:'completed'}
      : {type:'message',id,role:'assistant',status:'completed',content:[{type:'output_text',text,annotations:[]}]};
    const response={id,object:'response',model:'fixture',status:'completed',output:[item],usage:{input_tokens:20,output_tokens:10,total_tokens:30}};
    const truncated=mode==='review_truncated' && index===1;
    if(truncated) Object.assign(response,{status:'incomplete',incomplete_details:{reason:'max_output_tokens'}});
    const events=[{type:'response.created',response:{...response,status:'in_progress',output:[]}},
      {type:'response.output_item.added',output_index:0,item},{type:'response.output_item.done',output_index:0,item},{type:truncated?'response.incomplete':'response.completed',response}];
    return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
  }
  const chunk=(delta,finish_reason=null)=>'data: '+JSON.stringify({id,object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta,finish_reason}]})+'\n\n';
  const delta=operation ? {role:'assistant',tool_calls:[{index:0,id,type:'function',function:{name:operation.name,arguments:JSON.stringify(operation.args)}}]} : {role:'assistant',content:text};
  return new Response(chunk(delta)+chunk({},operation?'tool_calls':mode==='review_truncated'?'length':'stop')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
};
