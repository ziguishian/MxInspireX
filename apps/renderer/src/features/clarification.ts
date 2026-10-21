import type { ConversationMessage } from './pageServices';

export type Clarification = {
  intro?: string;
  questions: { id: string; question: string; options: string[]; multi?: boolean }[];
};
export type ClarificationAnswer = { selected: string[]; custom: string; useCustom: boolean; skipped: boolean };
export type StructuredAnswer = { questionId: string; questionIndex: number; value: string; skipped: boolean };
export type ClarificationSubmission = { taskId: string; answers: string; entries?: StructuredAnswer[] };
export function structuredAnswers(clarification: Clarification, answers: ClarificationAnswer[]): StructuredAnswer[] {
  return clarification.questions.map((question, index) => {
    const answer = answers[index] || emptyClarificationAnswer();
    return { questionId: question.id, questionIndex: index, skipped: answer.skipped, value: answer.skipped ? '' : [...answer.selected, ...(answer.useCustom && answer.custom.trim() ? [answer.custom.trim()] : [])].join('；') };
  });
}
export const emptyClarificationAnswer = (): ClarificationAnswer => ({ selected: [], custom: '', useCustom: false, skipped: false });

/** A later user message supersedes the old form; history must never reopen it. */
export function pendingClarification(messages: ConversationMessage[]) {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index];
    if (message.role === 'user') return null;
    if (message.role === 'assistant') {
      return message.taskId && message.clarification?.questions.length && (!message.status || message.status === 'succeeded')
        ? { taskId: message.taskId, clarification: message.clarification } : null;
    }
  }
  return null;
}

export function clarificationAnswered(answer: ClarificationAnswer) {
  return answer.selected.length > 0 || (answer.useCustom && Boolean(answer.custom.trim()));
}

export function clarificationReply(clarification: Clarification, answers: ClarificationAnswer[]) {
  return clarification.questions.map((question, index) => {
    const answer = answers[index] || emptyClarificationAnswer();
    const values = [...answer.selected, ...(answer.useCustom && answer.custom.trim() ? [answer.custom.trim()] : [])];
    return `${question.question}\n${answer.skipped ? '暂时跳过，尚未确定。' : values.join('；') || '尚未回答。'}`;
  }).join('\n\n');
}

/** Only restore drafts for exactly the same questions and available choices. */
export function restoreClarificationDraft(clarification: Clarification, raw: string | null) {
  const initial = { step: 0, answers: clarification.questions.map(emptyClarificationAnswer) };
  try {
    const saved = JSON.parse(raw || 'null');
    if (saved?.signature !== JSON.stringify(clarification.questions) || !Array.isArray(saved.answers)) return initial;
    const answers = clarification.questions.map((question, index) => {
      const answer = saved.answers[index] || {};
      const selected = [...new Set<string>((Array.isArray(answer.selected) ? answer.selected : []).filter((value: unknown) => typeof value === 'string' && question.options.includes(value)))];
      const useCustom = answer.useCustom === true;
      return { selected: question.multi ? selected : useCustom ? [] : selected.slice(0, 1), custom: typeof answer.custom === 'string' ? answer.custom.slice(0, 4000) : '', useCustom, skipped: answer.skipped === true };
    });
    return { step: Number.isInteger(saved.step) ? Math.max(0, Math.min(answers.length - 1, saved.step)) : 0, answers };
  } catch { return initial; }
}
