import { referencedKeys, type InlineReference } from './references';
import type { TaskReferenceSnapshot } from './messageReferences';
import type { ConversationMessage } from '../pageServices';

export type EditedTask = { conversationTurnId?: string; replacesTaskId?: string };

/** Keep the turn's position and identity, while clearing the superseded reply. */
export function replaceConversationTurn(messages: ConversationMessage[], task: EditedTask & { id: string; userMessage?: string; references?: TaskReferenceSnapshot; status: string }): ConversationMessage[] {
  if (!task.replacesTaskId) return messages;
  return messages.map(message => message.taskId !== task.replacesTaskId ? message : {
    role: message.role, taskId: task.id, conversationTurnId: task.conversationTurnId || message.conversationTurnId || message.taskId,
    content: message.role === 'user' ? task.userMessage || '' : '', status: task.status,
    ...(message.role === 'user' ? { referenceSnapshot: task.references } : {}),
  });
}

/** Reuse the edited message's inputs, never attachments in an unrelated draft. */
export function resubmissionReferences(originalText: string, text: string, original: TaskReferenceSnapshot, references: InlineReference[], added: TaskReferenceSnapshot): TaskReferenceSnapshot {
  const before = referencedKeys(originalText, references), after = referencedKeys(text, references);
  const keep = (key: string) => !before.has(key) || after.has(key);
  const assetKey = (item: NonNullable<TaskReferenceSnapshot['referencedAssets']>[number]) => `asset:${item.id || item.assetId}`;
  const nodeKey = (item: NonNullable<TaskReferenceSnapshot['referencedNodes']>[number]) => `node:${item.id || item.nodeId}`;
  const fileKey = (item: NonNullable<TaskReferenceSnapshot['referencedFiles']>[number]) => item.scope === 'global' ? `knowledge:${item.documentId}` : `file:${item.documentId || item.index || item.filename}`;
  const merge = <T>(old: T[], added: T[], key: (item: T) => string) => {
    const result = new Map(old.filter(item => keep(key(item))).map(item => [key(item), item]));
    for (const item of added) if (!result.has(key(item))) result.set(key(item), item);
    return [...result.values()];
  };
  const automatic = <T extends object>(item: T): T => {
    const next = { ...item } as T & { referenceMode?: unknown };
    delete next.referenceMode;
    return next;
  };
  const assets = merge(original.referencedAssets || [], added.referencedAssets || [], assetKey);
  const nodes = (original.referencedNodes || []).filter(node => {
    const id = node.id || node.nodeId;
    return after.has(nodeKey(node)) || !(original.referencedAssets || []).some(asset => asset.nodeId === id)
      || assets.some(asset => asset.nodeId === id);
  });
  return {
    ...(original.referencedSkills || added.referencedSkills ? { referencedSkills: merge(original.referencedSkills || [], added.referencedSkills || [], item => `skill:${item.id}`) } : {}),
    referencedAssets: assets.map(automatic),
    referencedNodes: merge(nodes, added.referencedNodes || [], nodeKey),
    referencedFiles: merge(original.referencedFiles || [], added.referencedFiles || [], fileKey).map(automatic),
  };
}
