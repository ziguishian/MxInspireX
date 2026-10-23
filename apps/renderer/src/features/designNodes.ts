export type Shot = { description: string; duration: number; camera: string };
export function cutoutModel(options: readonly string[]) {
  // Keep the provider's exact ID, including known 2.5 variants and dated IDs.
  return options.find(model => /^(?:openai\/)?gpt-image-2\.5-flare(?:-\d{4}-\d{2}-\d{2})?$/i.test(model)) || options.find(model => /^(?:openai\/)?gpt-image-2\.5(?:-(?:flare|sunburst))?(?:-\d{4}-\d{2}-\d{2})?$/i.test(model));
}
export function designNodeText(data: Record<string, any>): string {
  if (data.editor === 'palette') return `配色约束：${(data.colors || []).join('、')}。按顺序作为主色、辅助色与点缀色。`;
  if (data.editor === 'storyboard') return `视频分镜（按顺序在同一条视频中执行）：\n${(data.shots || []).map((s: Shot, i: number) => `${i + 1}. ${s.duration}秒；${s.description}；运镜：${s.camera || '自然平稳'}`).join('\n')}`;
  return String(data.html || data.text || data.summary || '');
}
export function storyboardDuration(data: Record<string, any>) {
  if (data.editor !== 'storyboard') return undefined;
  const shots = data.shots as Shot[];
  if (!shots?.length || shots.some(s => !s.description?.trim() || !Number.isInteger(s.duration) || s.duration < 1 || s.duration > 30)) throw new Error('请完善分镜画面描述与时长（1–30 整数秒）后再生成。');
  const total = shots.reduce((sum, s) => sum + s.duration, 0);
  if (total > 60) throw new Error('单条视频分镜总时长不能超过 60 秒，请拆成多个视频节点。');
  return total;
}
