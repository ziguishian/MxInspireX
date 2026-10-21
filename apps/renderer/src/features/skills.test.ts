import {afterEach,expect,test,vi} from 'vitest';
import {createSkillsApi,skillChatPrompt} from './skills';
afterEach(()=>vi.unstubAllGlobals());
test('API surfaces conflicts and field validation errors for a retry',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(Response.json({detail:'版本已被修改'},{status:409})).mockResolvedValueOnce(Response.json({detail:[{loc:['body','name'],msg:'invalid'}]},{status:422})).mockResolvedValueOnce(new Response('bad',{status:502})));
  const api=createSkillsApi('http://fixture.invalid');
  await expect(api('/a',{method:'PATCH'})).rejects.toThrow('版本已被修改');
  await expect(api()).rejects.toThrow('name：invalid');
  await expect(api()).rejects.toThrow('无法读取');
});

test('chat navigation keeps requirements under the new intent without duplicate creation requests',()=>{
  const create = skillChatPrompt('文旅包装，要有工艺检查');
  expect(create.startsWith('请帮我创建一个 Skill')).toBe(true);
  const edit = skillChatPrompt(create, {id:'packaging',title:'包装方法'});
  expect(edit.startsWith('请修改已安装的 Skill')).toBe(true);
  expect(edit).not.toContain('创建一个 Skill');
  expect(edit).toContain('文旅包装，要有工艺检查');
  expect(skillChatPrompt(skillChatPrompt(''))).toBe(skillChatPrompt(''));
});
