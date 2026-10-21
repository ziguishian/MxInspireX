import {describe,it,expect} from 'vitest';
import {portableResponsesRequest} from '../app/portable_responses.mjs';
import {getInputItems} from '../../../node_modules/@openai/agents-openai/dist/openaiResponsesConverter.mjs';
describe('portable Responses history',()=>{
  const request={previousResponseId:'resp_other',conversationId:'conv_other',modelSettings:{maxTokens:4096},input:[
    {type:'message',id:'msg_other',role:'assistant',content:[{type:'output_text',text:'设计方向'}]},
    {type:'function_call',id:'fc_other',callId:'call_1',name:'canvas_read',arguments:'{}',providerData:{id:'fc_other'}},
    {type:'function_call_result',callId:'call_1',output:'真实结果'},
    {type:'reasoning',id:'rs_other',content:[],providerData:{encrypted_content:'opaque'}},
    {type:'message',role:'user',content:[{type:'input_text',text:'沿用方向'}]},
  ]};
  it('keeps full tool pairs and messages without foreign resource ids or mutating history',()=>{
    const result=portableResponsesRequest(request,{provider:'evolink',api:'responses'});
    expect(result.input).toHaveLength(4);
    expect(result.input[1].callId).toBe(result.input[2].callId);
    expect(result.input[2].output).toBe('真实结果');
    expect(JSON.stringify(result)).not.toMatch(/msg_other|fc_other|rs_other|opaque|resp_other|conv_other/);
    expect(result.modelSettings).toEqual({maxTokens:4096,store:false});
    expect(request.input[0].id).toBe('msg_other');
    const wire=JSON.parse(JSON.stringify(getInputItems(result.input)));
    expect(wire[1]).toMatchObject({type:'function_call',call_id:'call_1',arguments:'{}'});
    expect(wire[2]).toMatchObject({type:'function_call_output',call_id:'call_1',output:'真实结果'});
    expect(JSON.stringify(wire)).not.toContain('_other');
  });
  it('leaves official endpoints and Chat Completions unchanged',()=>{
    expect(portableResponsesRequest(request,{provider:'openai',api:'responses'})).toBe(request);
    expect(portableResponsesRequest(request,{provider:'evolink',api:'chat_completions'})).toBe(request);
  });
});
