import { describe, expect, it } from 'vitest';
import { deliveryProgress, taskProgress } from './taskProgress';
import { structuredAnswers, emptyClarificationAnswer } from './clarification';
import type { DesignBatch, DeliveryProgress } from './taskProgress';

describe('design delivery UI data', () => {
  it('separates next-batch registration, current work and cumulative assets', () => {
    const old: DeliveryProgress = {id:'B1-1',title:'展架',kind:'image',status:'passed',nodeIds:['old']};
    const fresh: DeliveryProgress = {id:'B2-1',title:'海报',kind:'image',status:'pending'};
    const batch: DesignBatch = {version:1,intent:'next_batch',status:'needs_plan',number:2,itemIds:[],previousItemIds:[old.id],currentProgress:[]};
    const waiting = deliveryProgress({batch,plan:[old],deliverables:[old]});
    expect(waiting.total).toBe(0); expect(waiting.cumulativeReady).toBe(1);
    expect(waiting.cumulativeRows[0].status).toBe('passed');
    batch.status='ready';batch.itemIds=[fresh.id];batch.currentProgress=[fresh];
    const active = deliveryProgress({batch,plan:[old,fresh],deliverables:[old,fresh]});
    expect([active.ready,active.total,active.cumulativeReady,active.cumulativeTotal]).toEqual([0,1,1,2]);
    expect(active.rows.map(r=>r.id)).toEqual(['B2-1']);
    fresh.status='ready';
    const finished = deliveryProgress({batch,plan:[old,fresh],deliverables:[old,fresh]});
    expect([finished.ready,finished.cumulativeReady]).toEqual([1,2]);
  });
  it('keeps old output complete while a targeted revision is pending', () => {
    const old: DeliveryProgress = {id:'a',title:'展架',kind:'image',status:'passed'};
    const batch: DesignBatch = {version:1,intent:'revise',status:'ready',number:1,itemIds:['a'],previousItemIds:['a'],currentProgress:[{...old,status:'pending',issue:'等待本轮修改'}]};
    const progress=deliveryProgress({batch,deliverables:[old]});
    expect(progress.ready).toBe(0);expect(progress.cumulativeReady).toBe(1);
    expect(progress.rows[0].issue).toBe('等待本轮修改');
  });
  it('keeps question identity, position, custom answers and skips', () => {
    const questions = [{id:'same',question:'数量',options:[]},{id:'same',question:'规范',options:[]}];
    expect(structuredAnswers({questions},[{...emptyClarificationAnswer(),useCustom:true,custom:'300套'},{...emptyClarificationAnswer(),skipped:true}])).toEqual([
      {questionId:'same',questionIndex:0,value:'300套',skipped:false},{questionId:'same',questionIndex:1,value:'',skipped:true},
    ]);
  });
  it('does not count missing items or confuse generated with approved', () => {
    const progress = deliveryProgress({plan:[{id:'a',title:'外盒',kind:'image'},{id:'b',title:'内装',kind:'image'}],deliverables:[{id:'a',title:'外盒',kind:'image',status:'ready'}]});
    expect(progress.ready).toBe(1); expect(progress.total).toBe(2);
    expect(progress.rows[1].status).toBe('pending'); expect(progress.label(progress.rows[0])).toBe('已生成');
    expect(taskProgress({},'succeeded',Date.now(),true).label).toBe('等待补充需求');
    expect(taskProgress({deliverables:progress.rows},'succeeded').label).toBe('仍有待交付项');
    expect(deliveryProgress({deliverables:[{id:'cut',title:'刀版',kind:'image',status:'blocked',blockingFields:['dimensions']}]}).rows[0].blockingFields).toEqual(['尺寸']);
  });
});
