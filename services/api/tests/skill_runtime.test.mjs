import {test,expect} from 'vitest';
import {prepareModelInput} from '../app/sdk_context.mjs';
import {summarizeSkillHistory} from '../app/skill_runtime.mjs';
import {createToolScheduler} from '../app/tool_scheduler.mjs';
const user=text=>({type:'message',role:'user',content:[{type:'input_text',text}]});
const call=(name,id,args={})=>({type:'function_call',name,callId:id,arguments:JSON.stringify(args)});
const result=(name,id,body)=>({type:'function_call_result',name,callId:id,output:{type:'text',text:JSON.stringify(body)}});
test('active rules survive older turn cropping whole; capacity errors leave caller state unchanged',()=>{
  const instructions='规则'.repeat(11000),skills={active:[{skillId:'a',name:'a',title:'甲',version:1,contentHash:'hash',active:true,instructions}],bindings:[{skillId:'a',version:1,active:true}]};
  const input=[user('旧内容'.repeat(10000)),user('本轮要求'),call('canvas_read','read'),result('canvas_read','read',{nodes:[]})];
  const view=prepareModelInput({instructions:'核心',input},{skills,contextLength:64000});
  expect(view.modelData.input[0].content[0].text).toContain(instructions);
  expect(view.manifest.omitted).toBe(1);
  expect(view.modelData.input.filter(i=>i.callId==='read').map(i=>i.callId)).toEqual(['read','read']);
  const before=JSON.stringify(skills);
  expect(()=>prepareModelInput({input},{skills,contextLength:8000})).toThrow(/超出模型容量/);
  expect(JSON.stringify(skills)).toBe(before);
});
test('unload removes read bodies only from the model view and new tasks cannot inherit old read instructions',()=>{
  const input=[user('加载规则'),call('skill_read','r',{skill_id:'a'}),result('skill_read','r',{id:'a',instructions:'旧规则全文'}),
    call('skill_unload','u',{skill_id:'a'}),result('skill_unload','u',{skillId:'a',status:'succeeded',active:false})];
  expect(JSON.stringify(summarizeSkillHistory(input))).not.toContain('旧规则全文');
  expect(JSON.stringify(input)).toContain('旧规则全文');
  expect(JSON.stringify(summarizeSkillHistory([...input.slice(0,3),user('新的无关任务')]))).not.toContain('旧规则全文');
  expect(JSON.stringify(summarizeSkillHistory(input.slice(0,3)))).toContain('旧规则全文');
});
test('pending skill writes remain executable; completed bodies become summaries',()=>{
  const write=call('skill_create','c',{name:'a',instructions:'很长的创建正文'}),input=[user('创建'),write];
  expect(summarizeSkillHistory(input)[1].arguments).toBe(write.arguments);
  input.push(result('skill_create','c',{id:'a',version:1,status:'succeeded'}));
  expect(JSON.stringify(summarizeSkillHistory(input))).not.toContain('很长的创建正文');
  expect(input[1].arguments).toContain('很长的创建正文');
});
test('skill transitions serialize while an already submitted generation is preserved',async()=>{
  const scheduler=createToolScheduler(),started=[];
  let finish;const generation=new Promise(resolve=>finish=resolve);
  const jobs=[scheduler.run('generate_image',{},()=>{started.push('generation');return generation;}),
    ...['skill_load','skill_unload','skill_load'].map((name,i)=>scheduler.run(name,{},()=>{started.push(`${name}:${i}`);} ))];
  await new Promise(resolve=>setImmediate(resolve));expect(started).toEqual(['generation']);
  finish();await Promise.all(jobs);expect(started).toEqual(['generation','skill_load:0','skill_unload:1','skill_load:2']);
});
test('resource pages keep their whole 6000-character page until the model sees it',()=>{
  const page='参考'.repeat(2995)+'页尾验收条件';
  const input=[user('读取模板'),call('skill_read','read',{skill_id:'a',resource:'references/long.md'}),result('skill_read','read',{id:'a',text:page,nextOffset:6000})];
  const view=prepareModelInput({input},{contextLength:64000});
  expect(JSON.stringify(view.modelData.input)).toContain('页尾验收条件');
  expect(JSON.parse(view.modelData.input.at(-1).output.text).text).toBe(page);
});

test('failed writes retain arguments and actionable errors for correction',()=>{
  const input=[user('创建'),call('skill_create','failed',{name:'a',instructions:'保留待保存的方法',required_tools:['missing']}),
    {type:'function_call_result',callId:'failed',output:{type:'text',text:'An error occurred: 工具依赖不存在：missing'}}];
  expect(summarizeSkillHistory(input)).toEqual(input);
});

test('unknown model capacity keeps full active rules and does not turn a history budget into a hard limit',()=>{
  const instructions='完整业务规则'.repeat(1600);
  const skills={catalog:[{name:'notebook-print-design',description:'笔记本'}],active:[{active:true,name:'notebook-print-design',instructions}]};
  const view=prepareModelInput({instructions:'核心'.repeat(4500),input:[user('制作封面')]},{skills});
  expect(view.manifest.capacityKnown).toBe(false);
  expect(JSON.stringify(view.modelData.input)).toContain(instructions);
  expect(view.manifest.skillCatalogOmitted).toBe(1);
});

test('optional catalogue fits known capacity without truncating active rules or mutating bindings',()=>{
  const skills={catalog:Array.from({length:20},(_,i)=>({name:'skill-'+i,description:'很长的目录描述'.repeat(70)})),active:[{active:true,name:'active',instructions:'不能丢失的活跃规则'}]};
  const before=JSON.stringify(skills);
  const view=prepareModelInput({instructions:'核心',input:[user('当前要求')]},{skills,contextLength:8000});
  expect(view.manifest.skillCatalogOmitted).toBeGreaterThan(0);
  expect(JSON.stringify(view.modelData.input)).toContain('不能丢失的活跃规则');
  expect(JSON.stringify(skills)).toBe(before);
});

test('installing a catalogue cannot evict recent user constraints that fit without it',()=>{
  const old=user('必须保留的用户要求'+ '旧'.repeat(600)),current=user('新'.repeat(300));
  const skills={catalog:[{name:'optional',description:'目录'.repeat(1000)}]};
  const view=prepareModelInput({instructions:'核心'.repeat(3250),input:[old,current]},{skills});
  expect(JSON.stringify(view.modelData.input)).toContain('必须保留的用户要求');
  expect(view.manifest.skillCatalogOmitted).toBe(1);
});
