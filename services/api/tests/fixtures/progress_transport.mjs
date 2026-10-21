import assert from 'node:assert/strict';

// Real Agents SDK, deterministic transport; no account or network required.
const mode = process.env.PROGRESS_FIXTURE || 'complete';
const preamble = '我会基于引用图像修改配色，并保留原有构图。';
const answer = '配色修改已完成，可以在右侧画布查看。';
let round = 0;
globalThis.fetch = async (url, options) => {
  const body = JSON.parse(options.body);
  if (String(url).includes('/agent-tools/')) {
    assert.notEqual(mode,'truncated_tool','Truncated tool calls must never execute');
    assert.ok(String(url).endsWith('/report_progress'));
    assert.equal(body.summary, preamble);
    return Response.json({ summary: body.summary, status: 'recorded' });
  }
  const responses = String(url).endsWith('/responses');
  const tools = body.tools.map(tool => responses ? tool : tool.function);
  assert.ok(tools.some(tool => tool.name === 'report_progress'));
  if (['interrupted','no_terminal','truncated_tool','failed'].includes(mode)) assert.equal(round,0,'submitted incomplete responses must never replay');
  const first = round++ === 0;
  const withTool = mode === 'tool' && first;
  const text = withTool ? preamble : answer;
  const partial = text.slice(0, 9);
  if (!responses) {
    const chunk = (delta, reason = null) => ({ id: 'fixture', object: 'chat.completion.chunk', created: 1, model: body.model, choices: [{ index: 0, delta, finish_reason: reason }] });
    const events = [chunk({role: 'assistant', content: partial})];
    if (['interrupted','no_terminal','truncated_tool'].includes(mode)) {
      if (mode === 'truncated_tool') events.push(chunk({tool_calls:[{index:0,id:'partial-call',type:'function',function:{name:'report_progress',arguments:JSON.stringify({summary:preamble})}}]}));
      if (mode !== 'no_terminal') events.push(chunk({},'length'));
      return new Response(events.map(e=>`data: ${JSON.stringify(e)}\n\n`).join('')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
    }
    events.push(chunk({content: text.slice(9)}));
    if (withTool) events.push(chunk({tool_calls:[{index:0,id:'progress-call',type:'function',function:{name:'report_progress',arguments:JSON.stringify({summary:preamble})}}]}));
    events.push(chunk({}, withTool ? 'tool_calls' : 'stop'));
    return new Response(events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n', {headers:{'content-type':'text/event-stream'}});
  }
  const message = {type:'message',id:'message-'+round,role:'assistant',status:'completed',content:[{type:'output_text',text,annotations:[]}]};
  const call = {type:'function_call',id:'progress-call',call_id:'progress-call',name:'report_progress',arguments:JSON.stringify({summary:preamble}),status:'completed'};
  const response = {id:'response-'+round,object:'response',created_at:1,model:body.model,status:'completed',output:withTool?[message,call]:[message],usage:{input_tokens:10,output_tokens:8,total_tokens:18}};
  const events = [
    {type:'response.created',response:{...response,status:'in_progress',output:[]}},
    {type:'response.output_item.added',output_index:0,item:{...message,status:'in_progress',content:[]}},
    {type:'response.output_text.delta',item_id:message.id,output_index:0,content_index:0,delta:partial},
    // Raw private reasoning must never appear in public progress.
    {type:'response.reasoning_text.delta',delta:'PRIVATE_REASONING_SENTINEL'},
  ];
  if (['interrupted','truncated_tool','failed'].includes(mode)) {
    if (mode==='truncated_tool') events.push({type:'response.output_item.added',output_index:1,item:call});
    events.push({type:mode==='failed'?'response.failed':'response.incomplete',response:{...response,status:mode==='failed'?'failed':'incomplete',incomplete_details:mode==='failed'?null:{reason:'max_output_tokens'},output:[{...message,content:[{type:'output_text',text:partial,annotations:[]}]}]}});
  } else {
    events.push({type:'response.output_item.done',output_index:0,item:message});
    if (withTool) events.push({type:'response.output_item.added',output_index:1,item:call},{type:'response.output_item.done',output_index:1,item:call});
    // Deliberately omit the rest of the deltas. The final response is complete.
    events.push({type:'response.completed',response});
  }
  return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
};
