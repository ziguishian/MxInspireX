import assert from 'node:assert/strict';
import { appendFileSync } from 'node:fs';
const mode = process.env.NATIVE_SEARCH_FIXTURE || 'success';
globalThis.fetch = async (url, init) => {
  assert.ok(String(url).endsWith('/responses'), String(url));
  const body = JSON.parse(init.body);
  assert.ok(['web_search', 'openrouter:web_search'].includes(body.tools[0].type));
  if (body.tools[0].type === 'openrouter:web_search') {
    assert.equal(body.tools[0].parameters.engine, 'native');
    assert.equal(body.max_tool_calls, 1);
    assert.ok(!body.include?.includes('web_search_call.action.sources'));
  } else assert.ok(body.include.includes('web_search_call.action.sources'));
  assert.equal(body.tool_choice, 'required');
  assert.equal(body.plugins, undefined);
  assert.equal(body.stream, true);
  if (process.env.SEARCH_REQUEST_FILE) appendFileSync(process.env.SEARCH_REQUEST_FILE, JSON.stringify(body)+'\n');
  if (mode.startsWith('http')) return Response.json({error:{message:'fixture-secret unsupported search'}}, {status:Number(mode.slice(4))});
  if (mode === 'hang') return new Promise((_, reject) => {
    if (init.signal.aborted) reject(new Error('aborted'));
    else init.signal.addEventListener('abort', () => reject(new Error('aborted')), {once:true});
  });
  const source = {type:'url',url:'https://93.184.216.34/source',title:'原始资料'};
  const router = body.tools[0].type === 'openrouter:web_search';
  const annotations = (router || mode === 'annotations' || mode === 'server_usage') && mode !== 'no_sources';
  const noCall = ['no_search','server_usage'].includes(mode);
  const call = {id:'ws_1',type:'web_search_call',status:'completed',action:{type:'search',query:'fixture',sources:annotations || router || mode === 'no_sources' ? [] : [source]}};
  const message = {id:'msg_1',type:'message',role:'assistant',status:'completed',content:[{type:'output_text',text:'原生搜索摘要',annotations:annotations ? [{type:'url_citation',url:source.url,title:source.title,start_index:0,end_index:6}] : []}]};
  const response = {id:'resp_fixture',object:'response',created_at:1,model:body.model,status:mode === 'incomplete' ? 'incomplete' : 'completed',output:noCall ? [message] : [call,message],usage:{input_tokens:12,output_tokens:8,total_tokens:20,cost:.004,...(mode === 'server_usage' ? {server_tool_use_details:{web_search_requests:2}} : {})}};
  const events = [
    {type:'response.created',response:{...response,status:'in_progress',output:[]}},
    {type:'response.web_search_call.searching',item_id:call.id,output_index:0},
    ...(noCall ? [] : [{type:'response.output_item.done',output_index:0,item:call}]),
    {type:'response.output_item.done',output_index:1,item:message},
    {type:mode === 'incomplete' ? 'response.incomplete' : 'response.completed',response},
  ];
  if (mode === 'truncated') events.pop();
  return new Response(events.map(event=>'data: '+JSON.stringify(event)+'\n\n').join(''), {headers:{'content-type':'text/event-stream'}});
};
