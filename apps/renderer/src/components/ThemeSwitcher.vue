<script setup lang="ts">
import { computed, ref, useId } from 'vue';
import { Check, Monitor, Moon, Sun } from 'lucide-vue-next';
const mode = defineModel<'system' | 'light' | 'dark'>({ required: true });
const choices = [{ value: 'system', label: '跟随系统', icon: Monitor }, { value: 'light', label: '浅色模式', icon: Sun }, { value: 'dark', label: '深色模式', icon: Moon }] as const;
const active = computed(() => choices.find(item => item.value === mode.value)!);
const id = useId();
const menu = ref<HTMLElement>();
const trigger = ref<HTMLButtonElement>();
function select(value: typeof mode.value) { mode.value = value; menu.value?.hidePopover(); trigger.value?.focus(); }
function navigate(event: KeyboardEvent) {
  if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
  event.preventDefault();
  const buttons = [...(menu.value?.querySelectorAll('button') || [])];
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
  buttons[next]?.focus();
}
</script>
<template>
  <div class="mx-theme-switch">
    <button ref="trigger" type="button" :popovertarget="id" :aria-label="`界面主题：${active.label}`" :title="`界面主题：${active.label}`" aria-haspopup="menu"><component :is="active.icon" :size="18" :stroke-width="1.5" /></button>
    <div :id="id" ref="menu" popover class="mx-menu theme-menu" role="menu" aria-label="界面主题" @keydown="navigate">
      <button v-for="item in choices" :key="item.value" type="button" role="menuitemradio" :aria-checked="mode === item.value" @click="select(item.value)"><component :is="item.icon" :size="16" /><span>{{ item.label }}</span><Check v-if="mode === item.value" :size="15" /></button>
    </div>
  </div>
</template>
<style scoped>
.mx-theme-switch { border:0; padding:0; background:transparent; }
.mx-theme-switch > button { width:36px; height:36px; border:1px solid var(--theme-border); border-radius:50%; background:var(--theme-surface); anchor-name:--mx-theme-trigger; }
.theme-menu { position:fixed; inset:64px 24px auto auto; width:180px; margin:0; }
@supports (position-area: bottom) { .theme-menu { position-anchor:--mx-theme-trigger; inset:auto; position-area:bottom span-left; margin-top:8px; } }
.theme-menu button { display:flex; gap:10px; width:100%; height:36px; padding:8px 10px; border-radius:var(--ui-radius-control); font-size:var(--ui-font-control); }
.theme-menu button span { flex:1; text-align:left; }
</style>
