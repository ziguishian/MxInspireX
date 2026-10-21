import assert from 'node:assert/strict';

let round = 0, generationCalls = 0;
const [errorCode, message] = {
  format:['image_output_format','图像服务返回了 SVG，未返回要求的 PNG/JPEG/WebP 图片。'],
  timeout:['image_response_timeout','等待图像响应超时，生成结果待确认'],
  streaming:['image_streaming_unsupported','图像服务拒绝了流式响应模式，这不表示原图不支持编辑'],
}[process.env.FIXTURE_IMAGE_FAILURE || 'format'];
globalThis.fetch = async (input, options = {}) => {
  const url = String(typeof input === 'string' ? input : input.url);
  const body = JSON.parse(options.body || await input.text());
  if (url.includes('/agent-tools/generate_image')) {
    assert.equal(++generationCalls, 1, 'Never retry a returned but rejected image automatically');
    return Response.json({detail:message, errorCode, stopTool:true, retryable:false}, {status:422});
  }
  assert.match(url, /^http:\/\/fixture.invalid\/v1\/(responses|chat\/completions)$/, 'No external requests permitted');
  const index = round++, id = `format-${index}`;
  const first = index === 0 && process.env.FIXTURE_FORMAT_RESUME !== '1';
  const exposed = (body.tools || []).map(t => t.name || t.function?.name);
  assert.equal(exposed.includes('generate_image'), first);
  if (!first) {
    assert.ok(JSON.stringify(body).includes(errorCode));
    assert.equal(generationCalls, process.env.FIXTURE_FORMAT_RESUME === '1' ? 0 : 1);
  }
  const text = message + '已停止自动重试。';
  const args = JSON.stringify({prompt:'笔记本封面效果图'});
  if (url.endsWith('/responses')) {
    const item = first ? {type:'function_call',id:`fc-${id}`,call_id:id,name:'generate_image',arguments:args,status:'completed'}
      : {type:'message',id:`msg-${id}`,role:'assistant',status:'completed',content:[{type:'output_text',text,annotations:[]}]};
    const response = {id:`res-${id}`,object:'response',model:'fixture',status:'completed',output:[item],usage:{input_tokens:20,output_tokens:10,total_tokens:30}};
    const events = [{type:'response.created',response:{...response,status:'in_progress',output:[]}},
      {type:'response.output_item.added',output_index:0,item}, {type:'response.output_item.done',output_index:0,item}, {type:'response.completed',response}];
    return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
  }
  const chunk = (delta,finish_reason=null) => 'data: '+JSON.stringify({id,object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta,finish_reason}]})+'\n\n';
  const delta = first ? {role:'assistant',tool_calls:[{index:0,id,type:'function',function:{name:'generate_image',arguments:args}}]} : {role:'assistant',content:text};
  return new Response(chunk(delta)+chunk({},first?'tool_calls':'stop')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
};
