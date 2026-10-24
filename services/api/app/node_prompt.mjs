export const literalNode = constraints => constraints?.taskSurface === 'canvas_node' && constraints?.nodePrompt?.version === 1;
export function nodeToolAllowed(name, kind) {
  return ({text:['canvas_create_text', 'generate_text'],html:['canvas_create_html'],cad:['generate_cad']}[kind] || []).includes(name);
}
export function directNodeCall(constraints) {
  if (!literalNode(constraints)) return null;
  const canvas = constraints.canvasParams || {};
  const kind = canvas.kind === 'upload' ? 'image' : canvas.kind;
  if (!['image', 'video', 'audio'].includes(kind)) return null;
  return {name: `generate_${kind}`, args: {prompt: constraints.nodePrompt.submitted}};
}
export const nodeInstructions = `当前仅执行节点内容生成。节点提示词是完整的用户输入，不润色、不扩写、不检索提示词模板，不继承主对话设计要求。只使用用户提交的参数和图片附件；上游文字已由用户在输入框内确认，不再次拼接。只调用与节点类型匹配的生成或保存工具一次，将内容保存到当前空白节点，不额外生成图片或其他交付。HTML/CAD/文字可使用完成内容本身所需的模型能力，但不能增加前置提示词组织步骤。`;
