import {describe,it,expect} from 'vitest';
import {z} from 'zod';
import {supportsStrictTools,strictSchema,normalizeOptionalNulls,typedBatchSchema,applyToolContracts,imageParamsSchema} from '../app/tool_contracts.mjs';

describe('endpoint-aware tool contracts',()=>{
  const schema=z.toJSONSchema(z.object({prompt:z.string(),params:imageParamsSchema(z).optional(),note:z.string().optional(),nullable:z.string().nullable().optional()}));
  it('enables native decoding only with endpoint evidence',()=>{
    expect(supportsStrictTools({baseUrl:'https://api.openai.com/v1',model:'gpt-6-luna'})).toBe(true);
    for(const baseUrl of ['https://api.openai.com.fake/v1','https://api.openai-proxy.org/v1','http://api.openai.com/v1']) {
      expect(supportsStrictTools({baseUrl,model:'gpt-6-luna'})).toBe(false);
    }
    expect(supportsStrictTools({baseUrl:'https://openrouter.ai/api/v1'}, {supportedParameters:['tools','structured_outputs']})).toBe(true);
    expect(supportsStrictTools({baseUrl:'https://api.openai.com/v1',model:'gpt-6-luna'},{strictTools:false})).toBe(false);
  });
  it('closes nested schemas while retaining creative text and nullable business fields',()=>{
    const wire=strictSchema(schema);
    expect(wire.additionalProperties).toBe(false);
    expect(wire.required).toEqual(['prompt','params','note','nullable']);
    expect(wire.properties.params.anyOf[0].additionalProperties).toBe(false);
    expect(normalizeOptionalNulls({prompt:'完整的原创视觉描述',params:{size:null,quality:'low'},note:null,nullable:null},schema))
      .toEqual({prompt:'完整的原创视觉描述',params:{quality:'low'},nullable:null});
    expect(normalizeOptionalNulls({prompt:null},schema)).toEqual({prompt:null});
  });
  it('provides typed batch branches on compatible and unverified relays',()=>{
    const generators=[{name:'generate_image',parameters:schema}];
    const raw={tools:[{type:'function',name:'generate_batch',parameters:{type:'object'},strict:false}]};
    const unknown=applyToolContracts(raw,{baseUrl:'https://relay.invalid/v1'}, {},generators);
    expect(unknown.tools[0].strict).toBe(false);
    expect(unknown.tools[0].parameters).toEqual(typedBatchSchema(generators));
    const verified=applyToolContracts(raw,{baseUrl:'https://api.openai.com/v1',model:'gpt-6-luna'}, {},generators);
    const branch=verified.tools[0].parameters.properties.items.items.anyOf[0];
    expect(verified.tools[0].strict).toBe(true);
    expect(branch.properties.tool.const).toBe('generate_image');
    expect(branch.properties.arguments.required).toContain('prompt');
    expect(raw.tools[0].parameters).toEqual({type:'object'});
  });
  it('does not pretend arbitrary custom values have a strict schema',()=>{
    expect(()=>strictSchema(z.toJSONSchema(z.record(z.string(),z.any())))).toThrow();
    const result=applyToolContracts({tools:[{type:'function',name:'custom',parameters:{type:'object',properties:{params:{}},required:['params']}}]},
      {baseUrl:'https://api.openai.com/v1',model:'gpt-6-luna'}, {},[]);
    expect(result.tools[0].strict).toBe(false);
  });
});
