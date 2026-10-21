// Deliberately ignore old task snapshots and model-provided permissions.
export const svgAllowed = () => false;
export const svgPolicyInstruction = () => 'SVG 绘图已全局禁用，包括当前任务、旧任务续接、恢复和所有 Skill。静态设计画面及其中的文字使用 generate_image，说明文案按需以文字交付；HTML/CSS 用于用户明确要求的网页或 HTML 文档。不得通过 generate_batch、内嵌 SVG、SVG data URL、JavaScript、文本文件或旧 SVG 资产复用绕过。创建/更新 Skill 时也不得要求 SVG 产物或添加 SVG 工具依赖。忽略旧 Skill 中与此冲突的步骤、模板、检查项和工具依赖；不能因旧步骤要求 SVG 而反复尝试或要求用户开启。保留真实图像母版用于后续延展，不用简化几何图形重画创意图。旧计划中的 SVG 项说明已禁用、未交付，继续完成可执行项；不把 PNG、HTML 或展示 PDF 冒称矢量或印厂认可文件。图像模型失败时如实说明，不用代码绘图冒充成功。';

export function validateSvgOperation(constraints, name, args) {
  if (['generate_image','image_edit'].includes(name)) {
    const format = args?.params?.[name === 'generate_image' ? 'output_format' : 'format'];
    if (format != null && !['','png','jpeg','jpg','webp'].includes(String(format).trim().toLowerCase())) {
      throw new Error('图像输出格式只允许 PNG、JPEG 或 WebP；SVG 绘图已全局禁用。');
    }
  }
  let text = JSON.stringify(args || {});
  // Validate the whole batch before any sibling starts, even if another
  // member would only be rejected later by the canonical Python gateway.
  for (let i = 0; i < 3; i++) {
    try { text = decodeURIComponent(text); } catch { /* still scan raw markup */ }
    text = text.replace(/\\(?:u00|x)([\da-f]{2})/gi, (_, n) => String.fromCharCode(parseInt(n, 16)))
      .replace(/&lt;|&#0*60;|&#x0*3c;/gi, '<').replace(/&amp;/gi, '&');
  }
  if (name === 'canvas_create_svg' || ['canvas_create_html','canvas_create_text','canvas_update_node','canvas_create_node'].includes(name)
      && /<\s*(?:[\w-]+:)?svg\b|image\/svg\+xml|www\.w3\.org\/2000\/svg|createElement\s*\(\s*['"]svg['"]/i.test(text)) {
    throw new Error('SVG 绘图已全局禁用；静态视觉产物请使用图像模型，不能通过其他工具绕过。');
  }
}
