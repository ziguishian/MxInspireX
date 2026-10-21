import {describe, expect, it} from 'vitest';
import {agentOutputTokenLimit, responsesOutputFailure} from '../app/model_output.mjs';

describe('model output boundaries', () => {
  it('reserves enough space before a multi-item request without changing stored settings', () => {
    const input = {maxOutputTokens:4096, context:{constraints:{designPlanning:{required:true}}}};
    expect(agentOutputTokenLimit(input)).toBe(32768);
    expect(input.maxOutputTokens).toBe(4096);
    expect(agentOutputTokenLimit({...input,modelCapabilities:{max_output_tokens:16384}})).toBe(16384);
    expect(agentOutputTokenLimit({...input,modelCapabilities:{top_provider:{max_completion_tokens:65536}}})).toBe(32768);
    expect(agentOutputTokenLimit({context:{constraints:{designPlan:{deliverables:Array(7).fill({})}}}})).toBe(32768);
    expect(agentOutputTokenLimit({})).toBe(4096);
    expect(agentOutputTokenLimit({...input,context:{constraints:{...input.context.constraints,simpleConversation:true}}})).toBe(4096);
    for (const maxOutputTokens of [1024, 8192, 16384]) expect(agentOutputTokenLimit({...input,maxOutputTokens})).toBe(maxOutputTokens);
  });

  it('reserves space for explicit two/three-image tasks before an optional plan exists', () => {
    for (const count of [2, 3]) {
      const input = {context:{constraints:{deliveryContract:[{kind:'image',count}]}}};
      expect(agentOutputTokenLimit(input)).toBe(32768);
      expect(agentOutputTokenLimit({...input,modelCapabilities:{maxOutputTokens:8192}})).toBe(8192);
      expect(agentOutputTokenLimit({...input,maxOutputTokens:2048})).toBe(2048);
      expect(agentOutputTokenLimit({context:{constraints:{designPlan:{deliverables:Array(count).fill({kind:'image'})}}}})).toBe(32768);
    }
    expect(agentOutputTokenLimit({context:{constraints:{deliveryContract:[{kind:'image',count:1}]}}})).toBe(4096);
    expect(agentOutputTokenLimit({context:{constraints:{deliveryContract:[{kind:'image'},{kind:'text'}]}}})).toBe(32768);
  });

  it('treats incomplete Responses as submitted and unsafe to replay', () => {
    const failure=responsesOutputFailure({type:'response.incomplete',response:{status:'incomplete',incomplete_details:{reason:'max_output_tokens'}}});
    expect(failure.message).toContain('model_output_limit');
    expect(failure).toMatchObject({failureKind:'configuration',submitted:true,billingCertainty:'unknown',unsafeToReplay:true});
    expect(responsesOutputFailure({type:'response.failed',response:{status:'failed'}}).failureKind).toBe('provider');
    expect(responsesOutputFailure({type:'response.incomplete',response:{incomplete_details:{reason:'content_filter'}}}).message).not.toContain('model_output_limit');
    expect(responsesOutputFailure({type:'response.completed',response:{status:'completed'}})).toBeNull();
    expect(responsesOutputFailure({type:'response.output_item.done'})).toBeNull();
  });
});
