<script setup lang="ts">
import { computed, ref } from 'vue';
import { Check, RotateCcw } from 'lucide-vue-next';
import { appearance, themePalettes, colorsFor, validHex, contrastRatio } from '../features/appearance';
const mode = defineModel<'system' | 'light' | 'dark'>({ required: true });
const props = defineProps<{ resolved: 'light' | 'dark' }>();
const choices = [{ id: 'system', name: '跟随系统' }, { id: 'light', name: '浅色' }, { id: 'dark', name: '深色' }] as const;
const fields = [{ key: 'accent', name: '强调色' }, { key: 'background', name: '背景' }, { key: 'foreground', name: '文字' }] as const;
const colors = computed(() => colorsFor(props.resolved));
const error = ref('');
const lowContrast = computed(() => contrastRatio(colors.value.background, colors.value.foreground) < 4.5);
function updateColor(key: 'background' | 'foreground' | 'accent', value: string) {
  if (!validHex(value)) { error.value = '请输入完整的十六进制颜色，例如 #82A9E8。'; return; }
  error.value = '';
  if (appearance.preset !== 'custom') {
    appearance.custom = { dark: { ...colorsFor('dark') }, light: { ...colorsFor('light') } };
    appearance.preset = 'custom';
  }
  appearance.custom[props.resolved][key] = value.toLowerCase();
}
function reset() { appearance.preset = 'neutral'; appearance.font = 'system'; error.value = ''; }
</script>

<template>
  <section class="appearance-editor" aria-label="视觉风格">
    <header><h3>视觉风格</h3><small>自动保存 · 即时预览</small></header>
    <div class="appearance-mode-card"><strong>模式</strong><div class="appearance-mode-options" role="group" aria-label="显示模式">
      <button v-for="choice in choices" :key="choice.id" type="button" :aria-pressed="mode === choice.id" :aria-label="choice.name" @click="mode = choice.id">
        <span class="appearance-mini" :class="choice.id" aria-hidden="true"><i class="mini-sidebar"/><i class="mini-line first"/><i class="mini-line second"/><i class="mini-line third"/><i class="mini-composer"/></span>
        <span>{{ choice.name }}<Check v-if="mode === choice.id" :size="12" /></span>
      </button>
    </div></div>
    <div class="appearance-palette-card">
      <label class="appearance-setting-row"><strong>主题</strong><select v-model="appearance.preset" aria-label="主题配色"><option v-for="palette in themePalettes" :key="palette.id" :value="palette.id">{{ palette.name }}</option><option value="custom">自定义</option></select></label>
      <div class="appearance-swatches" role="group" aria-label="预设配色"><button v-for="palette in themePalettes" :key="palette.id" type="button" :aria-label="palette.name" :aria-pressed="appearance.preset === palette.id" @click="appearance.preset = palette.id; error = ''"><i :style="{background: palette[resolved].background, color: palette[resolved].accent, borderColor: palette[resolved].accent}"><Check v-if="appearance.preset === palette.id" :size="14"/><span v-else> Aa </span></i><small>{{ palette.name }}</small></button></div>
      <div v-for="field in fields" :key="field.key" class="appearance-setting-row"><strong>{{ field.name }}</strong><div class="appearance-color-control"><input type="color" :aria-label="`${field.name}选色器`" :value="colors[field.key]" @input="updateColor(field.key, ($event.target as HTMLInputElement).value)" /><input :key="`${resolved}:${appearance.preset}:${colors[field.key]}`" type="text" :aria-label="`${field.name}色值`" :value="colors[field.key].toUpperCase()" maxlength="7" spellcheck="false" @input="validHex(($event.target as HTMLInputElement).value) &amp;&amp; updateColor(field.key, ($event.target as HTMLInputElement).value)" @change="updateColor(field.key, ($event.target as HTMLInputElement).value.trim())" @keydown.enter.prevent="($event.target as HTMLInputElement).blur()" /></div></div>
      <label class="appearance-setting-row"><strong>字体</strong><select v-model="appearance.font" aria-label="界面字体"><option value="system">系统</option><option value="serif">衬线</option><option value="mono">等宽</option></select></label>
    </div>
    <footer><small>自定义颜色分别保存到深色和浅色模式，当前编辑{{ resolved === 'dark' ? '深色' : '浅色' }}。</small><button type="button" class="appearance-reset" @click="reset"><RotateCcw :size="14"/>恢复默认</button></footer>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="lowContrast" role="status">文字与背景对比度较低，建议调整颜色以便阅读。</p>
  </section>
</template>
