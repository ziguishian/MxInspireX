<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue';
import { Check, Copy, Pencil } from 'lucide-vue-next';
import UserMessageContent from './UserMessageContent.vue';
import type { ConversationMessage, MessageResubmission } from '../../features/pageServices';
import { readableReferences, referenceSegments } from '../../features/composer/references';
import { recordBetaUsage } from '../../features/betaTesting';
const props = defineProps<{ message: ConversationMessage; busy: boolean; editRequest?: number; resend: (submission: MessageResubmission) => Promise<boolean> }>();
const editing = ref(false), submitting = ref(false), copied = ref(false), error = ref(''), text = ref('');
const editor = ref<HTMLTextAreaElement | null>(null);
let copyTimer: ReturnType<typeof setTimeout> | undefined;
const references = computed(() => props.message.references || []);
async function copyMessage() {
  error.value = '';
  try {
    await navigator.clipboard.writeText(readableReferences(props.message.content, references.value));
    recordBetaUsage('message_copy', { taskId: props.message.taskId });
    copied.value = true;
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => { copied.value = false; }, 2000);
  } catch { error.value = '复制失败，请重试。'; }
}
async function editMessage() {
  recordBetaUsage('message_edit', { taskId: props.message.taskId });
  // Use readable names only when they resolve unambiguously back to the
  // original reference. Duplicate filenames retain their stable tokens.
  text.value = referenceSegments(props.message.content, references.value).map(part => {
    const alias = part.reference && `@${part.reference.label}`;
    return alias && part.reference?.aliases?.includes(alias) ? alias : part.text;
  }).join('');
  error.value = ''; editing.value = true;
  await nextTick(); editor.value?.focus();
}
async function resubmit() {
  if (props.busy || submitting.value || !text.value.trim() || !props.message.taskId) return;
  const content = referenceSegments(text.value, references.value).map(part => part.reference?.token || part.text).join('').trim();
  submitting.value = true; error.value = '';
  try {
    if (await props.resend({ taskId: props.message.taskId, text: content })) editing.value = false;
    else error.value = '修改尚未保存，请查看提示后重试。';
  } catch { error.value = '修改保存失败，编辑内容已保留。'; }
  finally { submitting.value = false; }
}
onUnmounted(() => clearTimeout(copyTimer));
watch(() => props.editRequest, request => { if (request && !submitting.value) void editMessage(); });
</script>

<template>
  <div class="user-message-bubble" :class="{ editing }">
    <div class="user-message-surface">
      <template v-if="editing">
        <textarea ref="editor" v-model="text" class="user-message-editor" aria-label="编辑消息内容" :disabled="submitting" rows="4" @keydown.meta.enter.prevent="resubmit" @keydown.ctrl.enter.prevent="resubmit" @keydown.esc.stop="!submitting && (editing = false)" />
        <div class="user-message-edit-footer"><span v-if="busy && !submitting">当前任务结束后可保存修改</span><button type="button" :disabled="submitting" @click="editing = false">取消</button><button type="button" class="message-resend" :disabled="busy || submitting || !text.trim()" @click="resubmit">{{ submitting ? '正在更新…' : '保存并重新提交' }}</button></div>
      </template>
      <UserMessageContent v-else :content="message.content" :references="references" />
    </div>
    <div v-if="!editing" class="user-message-actions" role="group" aria-label="消息操作">
      <button v-if="message.taskId" type="button" aria-label="编辑并重新提交" title="编辑并重新提交" @click.stop="editMessage"><Pencil :size="14" :stroke-width="1.7" /></button>
      <button type="button" :aria-label="copied ? '已复制' : '复制消息'" :title="copied ? '已复制' : '复制消息'" @click.stop="copyMessage"><Check v-if="copied" :size="14" /><Copy v-else :size="14" :stroke-width="1.7" /></button>
    </div>
    <span v-if="error" class="user-message-action-error" role="status">{{ error }}</span>
    <span v-if="copied" class="sr-only" role="status">消息已复制</span>
  </div>
</template>

<style scoped>
.user-message-bubble{position:relative;display:grid;justify-items:end;min-width:0}
.user-message-surface{box-sizing:border-box;min-width:0;max-width:100%;border:1px solid var(--theme-border);border-radius:16px 16px 4px 16px;background:var(--theme-surface-subtle);padding:12px 15px}
.user-message-actions{position:absolute;top:100%;right:0;z-index:1;display:flex;justify-content:flex-end;gap:2px;min-height:27px;margin-top:2px;opacity:0;pointer-events:none;transition:opacity .12s ease}
:global(.design-message.user:hover) .user-message-actions,.user-message-bubble:focus-within .user-message-actions{opacity:1;pointer-events:auto}
.user-message-actions button{display:grid;place-items:center;width:27px;height:27px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--theme-text-muted);cursor:var(--cursor-pointer)}
.user-message-actions button:hover{background:var(--theme-surface-hover);color:var(--theme-text)}
.user-message-actions button:focus-visible{outline:1px solid var(--theme-accent-strong);outline-offset:1px}
.user-message-bubble.editing{width:clamp(220px,28vw,650px);max-width:100%}
.user-message-bubble.editing .user-message-surface{width:100%}
.user-message-editor{display:block;box-sizing:border-box;width:100%;min-height:100px;max-height:40dvh;resize:vertical;border:0;outline:none;padding:0;background:transparent;color:var(--theme-text);font:inherit;font-size:14px;line-height:1.8}
.user-message-editor:focus-visible{box-shadow:0 1px 0 var(--theme-border-strong)}
.user-message-edit-footer{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:10px}
.user-message-edit-footer span{flex:1;color:var(--theme-text-muted);font-size:10px}
.user-message-edit-footer button{flex-shrink:0;border:0;border-radius:6px;padding:5px 8px;background:transparent;color:var(--theme-text-muted);font-size:11px;cursor:var(--cursor-pointer)}
.user-message-edit-footer .message-resend{color:var(--theme-accent-strong);background:var(--theme-surface-hover)}
.user-message-edit-footer button:disabled{opacity:.45;cursor:default}
.user-message-action-error{display:block;max-width:100%;color:var(--theme-danger);font-size:11px;margin-top:5px}
@media(hover:none){.user-message-actions{position:static;opacity:1;pointer-events:auto}}
@media(prefers-reduced-motion:reduce){.user-message-actions{transition:none}}
</style>
