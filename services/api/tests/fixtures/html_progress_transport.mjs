import assert from 'node:assert/strict';
const mode = process.env.HTML_PROGRESS_FIXTURE || 'complete';
const html = '<h1>PRIVATE_HTML_SENTINEL</h1><button>查看方案</button>';
const args = JSON.stringify({html,title:'完整网页'});
let round = 0, reserved = false, executed = false;
globalThis.fetch = async (url, options) => {
  const body = JSON.parse(options.body);
  if (String(url).endsWith('/html-preview')) {
    assert.equal(body.callId, 'html-call');
    if (body.state === 'started') reserved = true;
    else assert.ok(executed);
    return Response.json({nodeId:'html-node'});
  }
  if (String(url).includes('/agent-tools/')) {
    assert.ok(reserved); assert.equal(mode, 'complete');
    assert.ok(String(url).endsWith('/canvas_create_html'));
    assert.equal(body.html, html);
    assert.equal(options.headers['x-aics-html-preview-call-id'], 'html-call');
    executed = true;
    return Response.json({status:'succeeded',outputKind:'html',node:{id:'html-node',data:{kind:'html',html}}});
  }
  const responses = String(url).endsWith('/responses'), first = round++ === 0;
  if (first) {
    const tools = body.tools.map(tool => tool.function || tool);
    for (const name of ['canvas_create_html','design_plan','generate_image','generate_video','generate_audio']) {
      assert.ok(tools.some(tool=>tool.name===name), `Missing webpage tool: ${name}`);
    }
    assert.ok(!tools.some(tool=>tool.name==='generate_text'), 'Simple page copy stays in the main model');
    assert.ok(tools.find(tool=>tool.name==='canvas_create_html').parameters.properties.style_framework);
  }
  const chunk = (delta, finish_reason=null) => ({id:'fixture',object:'chat.completion.chunk',created:1,model:body.model,choices:[{index:0,delta,finish_reason}]});
  const call = {type:'function_call',id:'html-item',call_id:'html-call',name:'canvas_create_html',arguments:args,status:'completed'};
  const message = {type:'message',id:'message',role:'assistant',status:'completed',content:[{type:'output_text',text:'网页已保存到画布。',annotations:[]}]};
  const response = {id:'response-'+round,object:'response',created_at:1,model:body.model,status:'completed',output:[first?call:message],usage:{input_tokens:10,output_tokens:8,total_tokens:18}};
  const events = !first ? responses ? [{type:'response.completed',response}] : [chunk({role:'assistant',content:'网页已保存到画布。'}),chunk({},'stop')] : responses ? [
    {type:'response.created',response:{...response,status:'in_progress',output:[]}},
    {type:'response.output_item.added',output_index:0,item:{...call,arguments:'',status:'in_progress'}},
    {type:'response.function_call_arguments.delta',item_id:'html-item',output_index:0,delta:args.slice(0,10)},
    {type:'response.function_call_arguments.delta',item_id:'html-item',output_index:0,delta:args.slice(10)},
    ...(mode==='interrupted' ? [{type:'response.incomplete',response:{...response,status:'incomplete',incomplete_details:{reason:'max_output_tokens'}}}] : [{type:'response.output_item.done',output_index:0,item:call},{type:'response.completed',response}]),
  ] : [
    chunk({role:'assistant',tool_calls:[{index:0,id:'html-call',type:'function',function:{name:'canvas_create_html',arguments:args.slice(0,10)}}]}),
    chunk({tool_calls:[{index:0,function:{arguments:args.slice(10)}}]}),chunk({},mode==='interrupted'?'length':'tool_calls'),
  ];
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({async start(controller){
    for(let i=0;i<events.length;i++) {
      if(first && i===(responses?3:1)) {
        for(let n=0;n<100&&!reserved;n++) await new Promise(resolve=>setTimeout(resolve,10));
        assert.ok(reserved,'Placeholder must exist BEFORE complete HTML arguments arrive');
        assert.equal(executed,false);
      }
      controller.enqueue(encoder.encode(`data: ${JSON.stringify(events[i])}\n\n`));
    }
    controller.enqueue(encoder.encode('data: [DONE]\n\n'));controller.close();
  }}),{headers:{'content-type':'text/event-stream'}});
};
