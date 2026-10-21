import { ref } from 'vue';
import type { Board } from '../canvasEditing';

export type CanvasEdit = { before: Board; after: Board };
const histories = new Map<string, ReturnType<typeof createHistory>>();
const createHistory = () => ({ undo: ref<CanvasEdit[]>([]), redo: ref<CanvasEdit[]>([]) });

// Keep recent project history through page navigation; never store canvas content in localStorage.
export function canvasEditHistory(apiBaseUrl: string, projectId: string) {
  const key = JSON.stringify([apiBaseUrl, projectId]);
  const history = histories.get(key) || createHistory();
  histories.delete(key);
  histories.set(key, history);
  if (histories.size > 8) histories.delete(histories.keys().next().value!);
  return history;
}
