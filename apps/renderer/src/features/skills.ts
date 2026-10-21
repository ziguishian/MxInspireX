// Put the new intent first so an existing draft cannot change creation into a
// design run. Preserve user-written requirements, replacing only our own prefix.
export function skillChatPrompt(draft: string, skill?: {id:string;title:string}): string {
  const create = '请帮我创建一个 Skill，编写并保存到技能库，直到工具确认创建成功。我的需求是：';
  const requirements = draft.trim().replace(/^请帮我创建一个 Skill，编写并保存到技能库，直到工具确认创建成功。我的需求是：\s*/, '')
    .replace(/^请修改已安装的 Skill「[^\n]*」（ID：[^\n]*）。先读取当前版本，按以下要求更新并保存成功：\s*/, '');
  const prefix = skill ? `请修改已安装的 Skill「${skill.title}」（ID：${skill.id}）。先读取当前版本，按以下要求更新并保存成功：` : create;
  return prefix + '\n' + requirements;
}

export function createSkillsApi(baseUrl: string) {
  return async function request<T>(path='', init: RequestInit = {}): Promise<T> {
    const response=await fetch(`${baseUrl}/api/skills${path}`,{...init,headers:{'content-type':'application/json',...init.headers}});
    let body: any;
    try { body=await response.json(); } catch { throw new Error('技能库返回了无法读取的响应，请重试'); }
    if(!response.ok) {
      const detail=body.detail;
      throw new Error(typeof detail==='string' ? detail : Array.isArray(detail) ? detail.map(v=>`${v.loc?.slice(1).join('.') || '字段'}：${v.msg}`).join('；') : '技能库操作失败，请重试');
    }
    return body as T;
  };
}
