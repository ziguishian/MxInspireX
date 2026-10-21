// Wire contracts are derived from the same schemas used for local validation.
// Endpoint support is evidence based; an arbitrary OpenAI-compatible URL is
// not proof that the relay implements constrained tool decoding.
export function supportsStrictTools(endpoint = {}, capabilities = {}) {
  if (capabilities.strictTools === false) return false;
  if (capabilities.strictTools === true) return true;
  let url; try { url = new URL(endpoint.baseUrl); } catch { return false; }
  const model = String(endpoint.model || '').split('/').pop();
  if (url.origin === 'https://api.openai.com' && /^\/v1\/?$/.test(url.pathname)) {
    return /^(gpt-(?:4o|4\.1|[56])(?:[.-]|$)|o[134](?:-|$))/.test(model);
  }
  const params = capabilities.supportedParameters || [];
  return url.origin === 'https://openrouter.ai' && /^\/api\/v1\/?$/.test(url.pathname)
    && params.includes('tools') && params.includes('structured_outputs');
}

const nullable = schema => schema.type === 'null' || Array.isArray(schema.type) && schema.type.includes('null')
  || schema.anyOf?.some(nullable);

export function strictSchema(schema) {
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) throw new Error('Unsupported tool schema');
  const { $schema, default: _default, ...value } = schema;
  if (!value.type && !value.anyOf && !value.$ref && !value.enum) throw new Error('Unbounded tool value');
  const result = {...value};
  if (value.type === 'object') {
    if (!value.properties || !Object.keys(value.properties).length && value.additionalProperties !== false) throw new Error('Unbounded tool object');
    const required = new Set(value.required || []);
    result.properties = Object.fromEntries(Object.entries(value.properties).map(([key, child]) => {
      const converted = strictSchema(child);
      return [key, required.has(key) || nullable(converted) ? converted : {anyOf:[converted,{type:'null'}]}];
    }));
    result.required = Object.keys(result.properties);
    result.additionalProperties = false;
  }
  if (value.items) result.items = strictSchema(value.items);
  if (value.anyOf) result.anyOf = value.anyOf.map(strictSchema);
  if (value.$defs) result.$defs = Object.fromEntries(Object.entries(value.$defs).map(([k,v])=>[k,strictSchema(v)]));
  return result;
}

// Strict wire schemas express optional values as null. Remove only these
// sentinels; explicit nullable business values and required null errors stay.
export function normalizeOptionalNulls(value, schema) {
  if (!schema || value == null) return value;
  if (Array.isArray(value)) return value.map(item=>normalizeOptionalNulls(item,schema.items));
  if (typeof value !== 'object') return value;
  if (schema.anyOf) {
    const branch = schema.anyOf.find(s=>s.type==='object' && (!s.properties?.tool?.const || s.properties.tool.const===value.tool));
    if (branch) return normalizeOptionalNulls(value,branch);
  }
  const required = new Set(schema.required || []);
  return Object.fromEntries(Object.entries(value).filter(([key,item])=>
    !(item === null && schema.properties?.[key] && !required.has(key) && !nullable(schema.properties[key])))
    .map(([key,item])=>[key,normalizeOptionalNulls(item,schema.properties?.[key])]));
}

function compactSchema(schema) {
  if (Array.isArray(schema)) return schema.map(compactSchema);
  if (!schema || typeof schema !== 'object') return schema;
  return Object.fromEntries(Object.entries(schema).filter(([key])=>!['description','$schema','default'].includes(key)).map(([key,value])=>[key,compactSchema(value)]));
}

export function typedBatchSchema(generators) {
  return {type:'object',properties:{items:{type:'array',minItems:1,items:{anyOf:generators.map(({name,parameters})=>({
    type:'object',properties:{tool:{type:'string',const:name},deliverable_ids:{type:'array',items:{type:'string'},maxItems:50},arguments:compactSchema(parameters)},
    required:['tool','arguments'],additionalProperties:false,
  }))}}},required:['items'],additionalProperties:false};
}

export function applyToolContracts(request, endpoint, capabilities, generators) {
  const strict = supportsStrictTools(endpoint,capabilities);
  return {...request,tools:(request.tools || []).map(tool=>{
    if (tool.type !== 'function' || !tool.parameters) return tool;
    const parameters = tool.name === 'generate_batch' && generators.length ? typedBatchSchema(generators) : tool.parameters;
    if (strict) {
      try { return {...tool,parameters:strictSchema(parameters),strict:true}; } catch { /* Free-form tools retain their real schema. */ }
    }
    return {...tool,parameters,strict:false};
  })};
}

// Standard image controls advertised to the model. Gateway/UI settings still
// accept provider-specific extensions; no model is switched to fit a schema.
export function imageParamsSchema(z) {
  return z.looseObject({
    size:z.string().optional(),aspect_ratio:z.string().optional(),aspectRatio:z.string().optional(),
    image_size:z.string().optional(),resolution:z.string().optional(),quality:z.string().optional(),
    width:z.number().int().positive().optional(),height:z.number().int().positive().optional(),
    background:z.enum(['auto','opaque','transparent']).optional(),output_format:z.string().optional(),
    output_compression:z.number().int().optional(),seed:z.number().int().optional(),n:z.number().int().positive().optional(),
    style:z.string().optional(),moderation:z.string().optional(),input_fidelity:z.string().optional(),response_format:z.string().optional(),
  });
}
