import assert from 'node:assert/strict';
const mode=process.env.WEB_PIPELINE_MODE || 'success';
let round=process.env.WEB_PIPELINE_RESUME ? 1 : 0, saved=false;
const submitted=new Set(process.env.WEB_PIPELINE_RESUME ? ['欢迎试听。'] : []);
const updated=new Set();
const source='<button onclick="this.textContent=\'完成\'">切换</button><audio controls src="deliverable://sound"></audio>';
const media={status:'succeeded',assetId:'audio',node:{id:'audio-node',data:{kind:'audio',assetId:'audio',deliveryBinding:{scopeId:'scope',itemIds:['sound']}}}};
globalThis.fetch=async(input,options={})=>{
  const url=String(typeof input==='string'?input:input.url);
  assert.match(url,/^http:\/\/web-fixture.invalid\//,'Never access paid providers');
  if(url.endsWith('/updates'))return Response.json([]);
  if(url.includes('/audio-operations/')){
    assert.equal(options.method,'GET');
    assert.equal(round,2,'HTML must be authored before waiting on media');
    assert.equal(submitted.size,1);
    return Response.json(mode==='success'?{state:'completed',output:media}:{state:mode});
  }
  const body=JSON.parse(options.body || await input.text());
  if(url.endsWith('/html-preview'))return Response.json({nodeId:'page-node'});
  if(url.includes('/agent-tools/')){
    const name=url.split('/').at(-1);
    if(name==='canvas_update_node'){
      updated.add(body.node_id); saved=updated.size===2;
      return Response.json({status:'succeeded',node:{id:body.node_id,data:{kind:'text',text:body.patch.data.text,
        deliveryBinding:{scopeId:'scope',itemIds:[body.node_id]}}}});
    }
    if(name==='generation_reference_check')return Response.json({status:'ready'});
    if(name==='generate_audio'){
      assert.equal(options.headers['x-aics-async-tool'],'1');
      assert.equal(submitted.size,0,'Accepted media must not be resubmitted');
      submitted.add(body.prompt);
      return Response.json({state:'running',operationId:'original'},{status:202});
    }
    if(name==='canvas_create_html'){
      assert.equal(body.html,source,'Main model writes the page only once');
      if(mode!=='success')return Response.json({status:'dependency_required',submitted:false,instruction:'Original media unresolved'});
      saved=true;
      return Response.json({status:'succeeded',node:{id:'page-node',data:{kind:'html',html:source.replace('deliverable://sound','asset://audio'),deliveryBinding:{scopeId:'scope',itemIds:['page']}}}});
    }
    if(name==='delivery_verify' && mode==='updates')return Response.json({passed:saved,issues:[],artifacts:[],deliverables:
      ['a','b'].map(id=>({id,title:id,status:updated.has(id)?'ready':'pending',blockingFields:[]}))});
    if(name==='delivery_verify')return Response.json({passed:saved,issues:saved?[]:['媒体未完成'],artifacts:[],deliverables:[
      {id:'sound',title:'声音',status:mode==='success'?'ready':'pending',blockingFields:[]},
      {id:'page',title:'页面',status:saved?'ready':'blocked',blockingFields:[],blockingDeliverables:['sound']}]});
    throw new Error('Unexpected tool '+name);
  }
  assert.ok(round<2,'No extra model summary or media polling round');
  const index=round++,id='call-'+index;
  const name=mode==='updates'?'canvas_update_node':index===0?'generate_audio':'canvas_create_html';
  const args=JSON.stringify(mode==='updates'?{node_id:index===0?'a':'b',patch:{data:{text:'更新后的文字'}}}:
    index===0?{prompt:'欢迎试听。',deliverable_ids:['sound']}:{html:source,style_framework:'bootstrap',deliverable_ids:['page']});
  if(index===1 && mode!=='updates')assert.equal(submitted.size,1,'Original media starts before the HTML model call');
  if(url.endsWith('/responses')){
    const item={type:'function_call',id:'fc-'+id,call_id:id,name,arguments:args,status:'completed'};
    const response={id:'res-'+id,object:'response',model:'fixture',status:'completed',output:[item],usage:{input_tokens:20,output_tokens:10,total_tokens:30}};
    const events=[{type:'response.created',response:{...response,status:'in_progress',output:[]}},
      {type:'response.output_item.added',output_index:0,item},{type:'response.output_item.done',output_index:0,item},{type:'response.completed',response}];
    return new Response(events.map(event=>`data: ${JSON.stringify(event)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
  }
  const chunk=(delta,finish_reason=null)=>'data: '+JSON.stringify({id,object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta,finish_reason}]})+'\n\n';
  return new Response(chunk({role:'assistant',tool_calls:[{index:0,id,type:'function',function:{name,arguments:args}}]})+chunk({},'tool_calls')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
};
