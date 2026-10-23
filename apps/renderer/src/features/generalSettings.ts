import { reactive, watch } from 'vue';

export const generalDefaults = {
  notifications: true, sendWithEnter: true, restoreProject: true,
  focusNewOutputs: true, confirmProjectDelete: true, confirmAssetDelete: true,
  confirmNodeDelete: true,
};
export function readGeneralSettings(storage: Pick<Storage, 'getItem'>) {
  const result = { ...generalDefaults };
  try {
    const saved = JSON.parse(storage.getItem('aics.generalSettings') || '{}');
    for (const key of Object.keys(result) as (keyof typeof result)[]) {
      if (typeof saved?.[key] === 'boolean') result[key] = saved[key];
    }
  } catch { /* A damaged preference must not prevent startup. */ }
  return result;
}
export const generalSettings = reactive(readGeneralSettings({ getItem: key => typeof localStorage === 'undefined' ? null : localStorage.getItem(key) }));
watch(generalSettings, value => {
  try { localStorage.setItem('aics.generalSettings', JSON.stringify(value)); } catch { /* Keep this session usable. */ }
}, { flush: 'sync' });

export function shouldSendMessage(event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'altKey' | 'isComposing'>, enter: boolean) {
  return event.key === 'Enter' && !event.isComposing && !event.shiftKey && !event.altKey
    && (enter || event.ctrlKey || event.metaKey);
}
