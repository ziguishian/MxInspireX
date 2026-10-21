import { test, expect } from 'vitest';
import { cachedModelRequest, cacheUsage } from '../app/prompt_cache.mjs';
import { prepareModelInput } from '../app/sdk_context.mjs';
import { OpenAIChatCompletionsModel, OpenAIResponsesModel } from '@openai/agents-openai';
import OpenAI from 'openai';
import { withTrace, setTraceProcessors } from '@openai/agents';
setTraceProcessors([]);

const user = text => ({type:'message',role:'user',content:[{type:'input_text',text}]});
const request = { tracing:'disabled',systemInstructions:'稳定规则',input:[user('问题')],modelSettings:{maxTokens:100},tools:[],outputType:{type:'text'},handoffs:[] };
test('dynamic state and time stay after the reusable instructions and original turns in both APIs', () => {
  for (const api of ['responses','chat_completions']) {
    const first = prepareModelInput({instructions:'稳定规则',input:[user('请求')]},{api,frame:{clock:{nowUtc:'first'},notice:'不得重复生成'}});
    const second = prepareModelInput({instructions:'稳定规则',input:[user('请求')]},{api,frame:{clock:{nowUtc:'second'},notice:'不得重复生成'}});
    expect(first.modelData.instructions).toBe(second.modelData.instructions);
    expect(first.modelData.input[0]).toEqual(second.modelData.input[0]);
    expect(JSON.stringify(first.modelData.input.at(-1))).toContain('不得重复生成');
    expect(JSON.stringify(first.modelData.input.at(-1))).toContain('first');
    expect(JSON.stringify(second.modelData.input.at(-1))).toContain('second');
  }
});
test('canonical compact output, including retained old messages and tool pairs, survives local filtering intact', () => {
  const input=[{type:'compaction',encrypted_content:'opaque'},...Array.from({length:7},(_,i)=>user(`old-${i}`)),
    {type:'function_call',callId:'c',name:'canvas_read',arguments:'{}'},
    {type:'function_call_result',callId:'c',output:'正文'.repeat(3000)}, user('继续')];
  const prepared=prepareModelInput({input,instructions:'规则'},{contextLength:128000});
  expect(prepared.modelData.input).toEqual(input);
  expect(prepared.manifest.omitted).toBe(0);
});
test('unknown relays receive no unsupported cache controls; official and router keys remain stable across turns', () => {
  expect(cachedModelRequest(request,{baseUrl:'https://api.closeai.com/v1',model:'gpt-6-sol'},'project')).toBe(request);
  for (const baseUrl of ['https://api.openai.com/v1','https://openrouter.ai/api/v1']) {
    const endpoint={baseUrl,model:'gpt-6-sol'};
    const one=cachedModelRequest(request,endpoint,'project');
    const two=cachedModelRequest({...request,input:[...request.input,user('继续')]},endpoint,'project');
    expect(one.modelSettings.providerData.prompt_cache_key).toBe(two.modelSettings.providerData.prompt_cache_key);
    expect(one.modelSettings.providerData.prompt_cache_key).not.toContain('project');
    expect(cachedModelRequest(request,endpoint,'other').modelSettings.providerData.prompt_cache_key).not.toBe(one.modelSettings.providerData.prompt_cache_key);
    expect(one.input[0].providerData.content[0].prompt_cache_breakpoint).toEqual({mode:'explicit'});
    expect(one.systemInstructions).toBeUndefined();
    expect(one.modelSettings.promptCacheOptions.mode).toBe('explicit');
  }
  expect(cachedModelRequest(request,{baseUrl:'https://api.openai.com/v1',model:'gpt-4.1'},'project').modelSettings.promptCacheOptions).toBeUndefined();
});
test('installed SDK sends the cache boundary on the wire in both protocols without rewriting the original request', async () => {
  for (const api of ['responses','chat_completions']) {
    let body;
    const client=new OpenAI({apiKey:'fixture',baseURL:'https://openrouter.ai/api/v1',maxRetries:0,
      fetch:async (_url,options) => {
        body=JSON.parse(options.body);
        return Response.json(api==='responses'
          ? {id:'r',object:'response',status:'completed',output:[],usage:{input_tokens:10,output_tokens:0}}
          : {id:'r',object:'chat.completion',choices:[{index:0,message:{role:'assistant',content:'ok'},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:1}});
      }});
    const endpoint={baseUrl:'https://openrouter.ai/api/v1',model:'openai/gpt-6-sol',api};
    const model=api==='responses' ? new OpenAIResponsesModel(client,endpoint.model) : new OpenAIChatCompletionsModel(client,endpoint.model);
    await withTrace('cache wire fixture', () => model.getResponse(cachedModelRequest(request,endpoint,'project')), {disabled:true});
    expect(body.prompt_cache_options).toEqual({mode:'explicit',ttl:'30m'});
    expect(body.session_id).toBe(body.prompt_cache_key);
    expect((body.input || body.messages)[0].content[0].prompt_cache_breakpoint).toEqual({mode:'explicit'});
    expect(request.systemInstructions).toBe('稳定规则');
  }
});
test('cache usage distinguishes missing, zero, partial SDK arrays, and invalid counters', () => {
  expect(cacheUsage({input_tokens:100}).cache_reported_requests).toBe(0);
  expect(cacheUsage({input_tokens:100,input_tokens_details:{cached_tokens:0}}).cache_reported_requests).toBe(1);
  expect(cacheUsage({inputTokens:100,inputTokensDetails:[{cached_tokens:10,cache_write_tokens:20},{cached_tokens:5}]})).toMatchObject({cached_tokens:15,cache_write_tokens:20,cache_observed_input_tokens:100});
  expect(cacheUsage({prompt_tokens:100,prompt_tokens_details:{cached_tokens:70,cache_write_tokens:40}}).cache_reported_requests).toBe(0);
});
