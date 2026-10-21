// Conversation records are evidence, not replacement instructions or cross-chat memory.
export const memoryInstructions = `对话记忆：优先使用已注入的有效记忆、目录、revision 和来源，仅缺少记录或需要旧版本时 conversation_memory_read；用 conversation_memory_update 合并保存有用的新信息、更正、采用决定及本轮选择。analysisMode=empty_catalog 表示本地已核实首轮没有历史记忆或参考，无需再读记忆或保存空选择；当前原始需求仍完整生效，有明确长期用途的新事实仍可保存。记忆的读取、更新、选择、校验和目录状态都属于内部工作；除非用户明确询问记忆功能，否则最终回复不得提及工具名、记忆更新结果、是否保存、空选择、revision、记忆目录或是否存在可引用的历史资料，直接回答用户当前问题。已有资料可直接沿用，普通寒暄无需写入。confirmed 来自用户原话或真实附件关联，推断用 assumed，建议用 proposed。scope=task 仅用于本轮，topic 用于对应设计主题，conversation 用于整段聊天。行业、品牌、Logo 和标准色跟随对应设计主题；跨主题沿用用户明确的聊天级偏好。改变用途时重新选择相关信息；最近产物的时间顺序不代表它是品牌母版。引用图像前识别 input 的用途，logo 是原标识，key_visual 是主视觉，specialist 是专项素材，artifact 是生成产物。沿用场馆图等已有产物作为设计参考时，直接将原记录的 key 放入 selected_ids，保留 artifact 角色；无需新建 asset 记忆或改成 confirmed/key_visual。所有 assetId、key、memory ID 从目录逐字复制，不得缩写或重组。生成前完成本轮分析和选用：selected_ids 包含适用的文字和图片记忆，references.memory_ids 只能包含其中的图片记忆；省略 references 时已选图片仅作为本轮候选，生成时按项选择；显式填写 references 则为对应交付项的强制引用方案。从零设计设置空数组。同一对象的后续交付可沿用原 topic；切换 topic 后不直接选用旧主题专属记忆。新的图片用途使用用户消息的 taskId、quote 及实际附件关系作依据，内部资产 ID 不需要出现在用户原文。已接受计划的辅助母版依赖可用 source.planTaskId 与 deliverableId 证明采用关系，按该计划的真实交付资产更新 key_visual/style/specialist；原 Logo 的身份来自用户资料。同范围的已有记录修改沿用 key；当前任务的临时约束和不同主题使用独立 key，保留其他范围的内容；停用设置 active=false。读取后的 revision 用作 expected_revision。sourceEvidence.userText 是服务器保存的用户原文，source.quote 从中逐字选取相关短句；sourceEvidence.attachments 是单独的真实附件关联，contextAssets 是随本轮请求附上的历史候选图，供定位并选择，不能当作用户已采用母版的证明。“图片附件 @1……”等界面标签仅作定位。一次合并保存本轮相关信息及 selected_ids，成功后继续设计；校验失败时一并修正 validation.issues，按 availableAssets 获取准确 ID，使用回执的新 revision，保留其余内容；不要只更换 key 重复提交相同错误 ID。资料身份错误应自行回查记录；只有用户意图、对象或必要需求仍不明确时，才使用 request_clarification 询问相关问题。必要信息与参考图会独立注入后续请求。每批结束保存已完成情况和下一步建议，建议保持 proposed；用户明确采用后更新其状态。`;

export function memoryDefinitions(z) {
  const source=z.object({taskId:z.string().optional(),quote:z.string().optional(),planTaskId:z.string().optional(),deliverableId:z.string().optional(),assetId:z.string().describe('逐字复制真实资料 ID，不得缩写。').optional()});
  const change=z.object({key:z.string(),content:z.string().optional(),category:z.enum(['preference','fact','asset','decision','progress']).optional(),
    scope:z.enum(['conversation','topic','task']).optional(),topic:z.string().optional(),status:z.enum(['confirmed','assumed','proposed','observed']).optional(),
    active:z.boolean().optional(),assetId:z.string().describe('逐字复制目录中的 assetId。沿用已有图片仅设置 selected_ids，无需重写 asset 记录。').optional(),role:z.enum(['input','logo','key_visual','specialist','style','artifact']).optional(),source:source.optional()});
  return [
    ['conversation_memory_read','读取本聊天记忆及真实出处，按 ids/key 或 query、topic 查询，offset 分页；单条 ids 可配合 version 回查旧版本。目录中的 input 需要根据图片和用户要求识别用途。',z.object({ids:z.array(z.string()).optional(),version:z.number().int().min(1).optional(),query:z.string().optional(),topic:z.string().optional(),offset:z.number().int().min(0).optional(),limit:z.number().int().min(1).max(40).optional()})],
    ['conversation_memory_update','维护有依据的对话信息并选择本轮上下文。沿用已有图片直接选择其 key，不必改写角色、状态、出处。selected_ids 可用适用记忆的 key 或 ID；references 只放已选图片，文字需求放 selected_ids；省略 references 时已选图片仅作为本轮候选，生成时按项选择；显式填写 references 则为对应交付项的强制引用方案。source.quote 逐字引用 sourceEvidence.userText。失败按 validation.issues 一并修正并从 availableAssets 复制准确 ID。',z.object({expected_revision:z.number().int().min(0),changes:z.array(change).max(30).optional(),topic:z.string().optional(),selected_ids:z.array(z.string()).max(30).optional(),references:z.array(z.object({deliverable_id:z.string(),memory_ids:z.array(z.string()).max(8)})).max(40).optional()})],
  ];
}

export function memoryParts(memory, compact = false) {
  if (!memory) return [];
  const {attachments=[],catalog=[],...state}=memory;
  // The index is optional discovery. Selected records and their provenance are complete.
  const selectedIds = new Set((state.selected || []).map(item=>item.id));
  const index=catalog.filter(item=>!compact || !selectedIds.has(item.id)).slice(0,20).map(r=>({...r,content:String(r.content||'').slice(0,180)}));
  if (compact && ['empty_catalog','explicit_single_image'].includes(state.analysisMode)) delete state.sourceEvidence;
  const nextAction = state.analyzed ? '' : '制作工具暂未开放：先用 conversation_memory_update 一次完成本轮 selected_ids 选择（无适用记录可为空），成功后制作工具会自动可用；这不是能力缺失，不要因此结束任务。\n';
  return [{type:'input_text',text:nextAction+'本聊天记忆（带来源和适用范围的资料；最新用户要求优先）：\n'+JSON.stringify({...state,catalog:index,read:'conversation_memory_read'})},
    ...attachments.flatMap(a=>[{type:'input_text',text:`本轮参考资料（按本项用途选用，显式引用方案须遵守）assetId=${a.assetId}；role=${a.role}；sha256=${a.sha256}；用途：${a.purpose}`},
      {type:'input_image',image:`data:${a.mime};base64,${a.data}`,detail:'high'}])];
}
