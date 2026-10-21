// Only repair unambiguous envelopes. Never invent missing design decisions or
// generation parameters, and never retry a dispatched provider request here.
const planFields = ['goal','preserve','visualDirection','currentItemIds','deliverables','visualSeries','coverage','deferred','openQuestions','research'];
export class ToolInputNormalizationError extends Error {
  constructor(path, message) { super(message); this.issues = [{path, code:'custom', message}]; }
}

export function currentDesignPlan(constraints = {}, outputs = []) {
  return [...outputs].reverse().find(item => item.name === 'design_plan' && item.output?.plan)?.output.plan || constraints.designPlan;
}

export function bindPlanVersion(args, version) {
  if (!args?.plan || !version) return args;
  // The compare-and-swap token belongs to the model request's observed plan,
  // never to the model's guessed value or the unrelated design_state revision.
  return {...args,expected_revision:version.revision,expected_scope_id:version.scopeId};
}

export function reusesReadyPlan(args, plan, batch) {
  const noChange = args?.change_reason == null || typeof args.change_reason === 'string' && !args.change_reason.trim();
  return Boolean(plan?.ready && batch?.status !== 'needs_plan' && noChange
    && (args?.plan && Object.keys(args.plan).length || planFields.some(key => args?.[key] !== undefined)));
}

export function normalizeToolInput(name, args, constraints = {}) {
  if (name !== 'design_plan' || !args || typeof args !== 'object') return args;
  const value = structuredClone(args);
  if (value.plan === null || (value.plan && typeof value.plan === 'object' && !Array.isArray(value.plan) && !Object.keys(value.plan).length)) delete value.plan;
  if (!value.plan && planFields.some(key => value[key] !== undefined)) value.plan = {};
  if (value.plan && typeof value.plan === 'object' && !Array.isArray(value.plan)) {
    for (const key of planFields) {
      if (value[key] === undefined) continue;
      if (value.plan[key] !== undefined && JSON.stringify(value.plan[key]) !== JSON.stringify(value[key])) {
        throw new ToolInputNormalizationError(['plan',key], `plan.${key} 与外层 ${key} 不一致；请只保留一个明确值。`);
      }
      value.plan[key] = value[key]; delete value[key];
    }
    const areas = constraints.designPlanning?.areas || [];
    for (const item of Array.isArray(value.plan.coverage) ? value.plan.coverage : []) {
      const label = String(item?.area || '').replace(/^[一二三四五六七八九十百\d]+项/u, '');
      const area = areas.find(area => [area.id,area.title,...(area.aliases || [])].includes(label));
      if (area) item.area = area.id;
    }
  }
  return value;
}

export function inputFailure(name, error) {
  const issues = Array.isArray(error?.issues) ? error.issues : [];
  const fields = issues.map(issue => ({
    path: (issue.path || []).map(String).join('.'),
    code: String(issue.code), message: String(issue.message).slice(0, 250),
  }));
  return {tool:name, status:'invalid_arguments', code:'tool_input',
    // Stable recovery signature prevents changing an item index to reset the
    // correction budget. Individual errors still carry exact numeric paths.
    fieldPath: [...new Set(issues.map(issue=>(issue.path || []).map(part=>typeof part==='number'?'*':String(part)).join('.')))].sort().join('|') || '$',
    errors:fields, submitted:false,
    instruction: fields.length ? `仅修正 ${name} 的以下参数字段后重试；没有发起生成。${name === 'generate_batch' ? '保留已有 ready 计划，不要重写 design_plan。每项格式为 {tool:"generate_image",deliverable_ids:["已有交付ID"],arguments:{prompt:"本项提示词"}}，其他媒体使用对应工具名。' : ''}` : '工具参数不是有效 JSON 对象；修正格式后重试，没有发起生成。',
  };
}

export function validateBatchArguments(items, schemas, normalize = value=>value) {
  const issues = [], operations = [];
  for (const [index,item] of items.entries()) {
    const schema = schemas.get(item.tool);
    let result;
    try { result = schema?.safeParse(normalize(item.arguments,item.tool)); }
    catch(error) {
      if (!Array.isArray(error?.issues)) throw error;
      issues.push(...error.issues.map(issue=>({...issue,path:['items',index,'arguments',...issue.path]})));
      continue;
    }
    if (result?.success) operations.push({tool:item.tool,arguments:result.data});
    else for (const issue of result?.error.issues || [{path:[],code:'custom',message:'未知生成工具'}])
      issues.push({...issue,path:['items',index,'arguments',...issue.path]});
  }
  if (issues.length) {
    const error = new ToolInputNormalizationError([], '请一次修正全部条目的参数；整批尚未提交。');
    error.issues = issues;
    throw error;
  }
  return operations;
}

export function planReceipt(result) {
  // Control fields must survive size bounding; full plan remains in the
  // canonical tool receipt and the next model frame.
  const {tool, status, instruction, ...rest} = result;
  return {tool, status, instruction, ...rest};
}
