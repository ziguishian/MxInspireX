export type LumoReaction = 'calm' | 'happy' | 'wink';

export type TimedLumoMessage = {
  id: string;
  text: string;
  reaction: LumoReaction;
};

const at = (date: Date, hour: number, minute: number) => date.getHours() === hour && date.getMinutes() === minute;

export function timedLumoMessage(date: Date): TimedLumoMessage | null {
  if (at(date, 4, 42)) return { id: 'cosmic-0442', text: '现在是 4:42，宇宙正在偷偷保存你的灵感。', reaction: 'wink' };
  if (at(date, 8, 42)) return { id: 'morning-0842', text: '早上 8:42，今天的第一个好问题已经醒了。', reaction: 'happy' };
  if (at(date, 13, 37)) return { id: 'creative-1337', text: '13:37，灵感正在以不讲道理的方式变酷。', reaction: 'wink' };
  if (at(date, 23, 42)) return { id: 'save-2342', text: '23:42，宇宙建议：先保存，再继续伟大。', reaction: 'calm' };
  if (date.getHours() === 12 && date.getMinutes() < 5) return { id: 'lunch', text: '先去吃饭吧，空腹做出的留白容易太多。', reaction: 'happy' };
  if (date.getHours() < 5) return { id: 'late-night', text: '凌晨的灵感很亮，但你也值得睡一觉。', reaction: 'calm' };
  return null;
}

export function timedLumoStorageKey(message: TimedLumoMessage, date: Date): string {
  const day = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
  return `langjuart.lumoTimedMessage.${message.id}.${day}`;
}
