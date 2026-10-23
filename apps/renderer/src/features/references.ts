export type VisualReference = {
  id: string; title: string; thumbnailUrl: string; contentUrl: string;
  width: number; height: number; saved: boolean; analysisStatus: string; analysisError?: string;
  industries?: string[]; designTypes?: string[]; tags?: string[]; colors?: string[];
  description?: string; notes?: string; sourceUrl?: string; author?: string; rightsStatus?: string;
  direction?: string; reason?: string;
  evidenceType?: 'design_case' | 'product_photography' | 'material_process';
};
export type DesignLesson = { id: string; mediaKind: 'image' | 'html' | 'video' | 'cad'; tags: string[]; strategy: string; avoid: string[]; createdAt: string };
export type ReferenceSelection = { id: string; taskId: string; intro: string; items: VisualReference[]; errors?: { message: string; url?: string }[]; status: string; selected?: { id: string; aspects: string[] }[]; notes?: string; submittedAction?: string };
export type ReferenceSubmission = { id: string; action: 'confirm' | 'refresh' | 'skip'; selected?: { id: string; aspects: string[] }[]; notes?: string };
export function referenceUrl(base: string, path: string) {
  return /^\/api\/references\/[a-zA-Z0-9-]+\/(?:thumbnail|content)$/.test(path) ? base + path : '';
}
export async function referenceRequest<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(base + '/api/references' + path, init);
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '参考库操作失败');
  return body;
}
export const referenceAspects = ['造型语言','材质工艺','色彩关系','构图/信息层级','光影摄影','排版字体'] as const;
export function selectedReferenceEntries(card: ReferenceSelection, ids: string[], aspects: Record<string, string[]> = {}) {
  return card.items.filter(item => ids.includes(item.id)).map(item => ({ id: item.id, aspects: aspects[item.id]?.length ? aspects[item.id] : ['造型语言'] }));
}
export function pendingReferenceSelection(messages: { role: string; referenceSelection?: ReferenceSelection; status?: string }[]) {
  const last = messages.at(-1);
  if (last?.role !== 'assistant' || last.status !== 'succeeded') return undefined;
  for (const message of [...messages].reverse()) {
    if (message.referenceSelection) return message.referenceSelection.items.length && message.referenceSelection.status === 'pending' && !message.referenceSelection.submittedAction ? message.referenceSelection : undefined;
  }
  return undefined;
}


export function referenceTextChoices(card: ReferenceSelection, text: string) {
  if (/还是|或者|不确定|也许|不喜欢|不要第/.test(text)) return [];
  const matches = [...text.matchAll(/第?\s*([0-9]+|[一二三四五六七八九十]+)\s*张/g)];
  const choices: { id: string; aspects: string[] }[] = [];
  for (const [index, match] of matches.entries()) {
    const ordinal = /^\d+$/.test(match[1]) ? Number(match[1]) : match[1].length === 1 ? '一二三四五六'.indexOf(match[1]) + 1 : 0;
    if (ordinal < 1 || ordinal > card.items.length) return [];
    const section = text.slice((match.index || 0) + match[0].length, matches[index + 1]?.index);
    const aliases:Record<string,string> = {'配色':'色彩关系','构图':'构图/信息层级','排版':'排版字体','材质':'材质工艺','字体':'排版字体','整体风格':'造型语言'};
    const aspects = Object.entries(aliases).filter(([value]) => section.includes(value)).map(([,value]) => value);
    choices.push({ id: card.items[ordinal-1].id, aspects: aspects.length ? [...new Set(aspects)] : ['造型语言'] });
  }
  return choices;
}
