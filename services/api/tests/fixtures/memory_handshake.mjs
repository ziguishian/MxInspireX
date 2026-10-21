// Give older workflow fixtures an explicit no-facts memory analysis step.
// Dedicated memory_transport exercises semantic writes and reference selection.
export function memoryHandshake(body) {
  const texts=[];
  const visit=value=>{
    if(typeof value==='string' && value.startsWith('本聊天记忆（'))texts.push(value);
    else if(value && typeof value==='object')for(const child of Object.values(value))visit(child);
  };
  visit(body.input || body.messages);
  if(!texts.length)return;
  const memory=JSON.parse(texts.at(-1).split('\n').slice(1).join('\n'));
  if(memory.analyzed)return;
  const args=JSON.stringify({expected_revision:memory.revision,changes:[],selected_ids:[]});
  const id=`memory-fixture-${memory.revision}`;
  if(body.input) {
    const item={type:'function_call',id,call_id:id,name:'conversation_memory_update',arguments:args,status:'completed'};
    const response={id:'res-'+id,object:'response',model:body.model,status:'completed',output:[item],usage:{input_tokens:10,output_tokens:8,total_tokens:18,input_tokens_details:{cached_tokens:2}}};
    const events=[{type:'response.created',response:{...response,status:'in_progress',output:[]}}, {type:'response.output_item.added',output_index:0,item},{type:'response.output_item.done',output_index:0,item},{type:'response.completed',response}];
    return new Response(events.map(e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),{headers:{'content-type':'text/event-stream'}});
  }
  const chunk=(delta,finish_reason=null)=>'data: '+JSON.stringify({id,object:'chat.completion.chunk',created:1,model:body.model,choices:[{index:0,delta,finish_reason}]})+'\n\n';
  return new Response(chunk({role:'assistant',tool_calls:[{index:0,id,type:'function',function:{name:'conversation_memory_update',arguments:args}}]})+chunk({},'tool_calls')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
}
