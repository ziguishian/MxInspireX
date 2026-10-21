<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { Check, Download, LoaderCircle, RotateCcw, Sparkles } from 'lucide-vue-next';
import { mascotFrames, mascotImageUrl, mascotPresets, mascotPresetImageUrl, useMascotSettings, type MascotProvider } from '../features/home/mascot';

const props = defineProps<{ provider: MascotProvider; modelOptions: string[] }>();
const mascot = useMascotSettings()!;
const { active, activePreset, activeName, latest, running, saving, loading, ready, uncertain, error } = mascot;
const prompt = ref('');
const model = ref('');
const selectedFrame = ref(0);
const previewTheme = ref<'light' | 'dark'>('dark');
const preview = computed(() => latest.value?.status === 'succeeded' ? latest.value : active.value);
const previewUrl = computed(() => mascotImageUrl(mascot.apiBaseUrl, preview.value));
const applied = computed(() => preview.value && active.value?.id === preview.value.id);
const blocked = computed(() => running.value || saving.value || loading.value || uncertain.value || !ready.value);
const validPrompt = computed(() => prompt.value.trim().length >= 4 && prompt.value.length <= 2000);
const remoteProvider = computed(() => ['openrouter', 'openai-compatible', 'openai-image', 'evolink'].includes(props.provider.key));
watch(() => latest.value?.id, () => { if (!prompt.value && latest.value) prompt.value = latest.value.prompt; }, { immediate: true });
watch(() => props.provider.key + props.provider.baseUrl, () => { model.value = ''; });
onMounted(() => { void mascot.load(); });
</script>

<template>
  <section class="mascot-settings" aria-labelledby="mascot-settings-title">
    <header><div><h3 id="mascot-settings-title">Agent 吉祥物</h3><p>首页和项目对话共用同一个设计搭档，也可以用文字创造自己的小伙伴。</p></div><span class="mascot-badge">{{ activeName }}</span></header>
    <div class="mascot-presets" role="group" aria-label="选择内置吉祥物">
      <button v-for="preset in mascotPresets" :key="preset.id" type="button" class="mascot-preset" :aria-pressed="activePreset === preset.id" :aria-label="`使用${preset.name}`" :disabled="saving || loading || !ready" @click="mascot.applyPreset(preset.id)">
        <span class="mascot-preset-art" :style="{ backgroundImage:`url(${mascotPresetImageUrl(preset.id)})`, backgroundPosition:preset.positions[0] }" aria-hidden="true" />
        <span class="mascot-preset-name"><strong>{{ preset.name }}</strong><Check v-if="activePreset === preset.id" :size="14" aria-hidden="true" /></span><small>{{ preset.description }}</small>
      </button>
    </div>
    <p class="mascot-hint" role="status"><i v-if="ready && !saving && !error" class="mascot-status is-ready" />{{ saving ? '正在保存吉祥物…' : loading && !ready ? '正在读取吉祥物设置…' : `当前：${activeName}。点击预设即刻应用，无需生成、不产生调用费用。` }}</p>
    <div v-if="error" class="mascot-error" role="alert">{{ error }} <button type="button" class="ghost-button" :disabled="loading" @click="mascot.load()">刷新状态</button></div>
    <h4 class="mascot-custom-title">自己创造一个</h4>
    <label class="mascot-label" for="mascot-prompt">形象描述</label>
    <textarea id="mascot-prompt" v-model="prompt" rows="4" maxlength="2000" :disabled="blocked" placeholder="例如：一只戴圆框眼镜的奶油色小猫，柔软的黏土质感，薄荷绿围巾，小爪子搭在输入框边缘。" />
    <div class="mascot-hint"><span>系统会补齐透明背景、六个表情与对齐要求。</span><span>{{ prompt.length }} / 2000</span></div>
    <label class="mascot-label" for="mascot-model">生成模型</label>
    <select id="mascot-model" v-model="model" :disabled="blocked"><option value="">跟随全局图像模型{{ provider.manual && provider.model ? ` · ${provider.model}` : ' · 自动选择' }}</option><option v-for="option in modelOptions" :key="option" :value="option">{{ option }}</option></select>
    <p class="mascot-hint">每次生成 1 张图集，使用创意档并按图像服务实际用量计费。需要支持透明背景的模型。</p>
    <p v-if="!remoteProvider" class="mascot-error">请先到“模型与连接”配置图像服务。</p>
    <div class="mascot-actions">
      <button type="button" class="primary-button" :disabled="blocked || !validPrompt || !remoteProvider" @click="mascot.generate(prompt, provider, model)"><LoaderCircle v-if="running || saving" :size="16" class="mascot-spinner" /><Sparkles v-else :size="16" />{{ running ? '正在生成图集…' : '生成吉祥物' }}</button>
      <button v-if="active || activePreset !== 'robot'" type="button" class="ghost-button" :disabled="saving || loading" @click="mascot.apply(null)"><RotateCcw :size="15" />恢复默认</button>
    </div>
    <p v-if="running" class="mascot-hint" role="status"><i class="mascot-status is-pending" />图集正在制作，切换页面后仍会继续；完成后可在这里预览和应用。</p>
    <p v-else-if="latest?.status === 'failed'" class="mascot-error" role="alert"><i class="mascot-status is-failed" />{{ latest.error }}</p>

    <div v-if="preview && previewUrl" class="mascot-preview">
      <div class="mascot-preview-heading"><strong>图集预览</strong><div class="mascot-preview-themes" role="group" aria-label="吉祥物预览背景"><button type="button" :aria-pressed="previewTheme === 'dark'" @click="previewTheme = 'dark'">深色</button><button type="button" :aria-pressed="previewTheme === 'light'" @click="previewTheme = 'light'">浅色</button></div></div>
      <div class="mascot-stage" :class="previewTheme"><span role="img" :aria-label="`吉祥物 · ${mascotFrames[selectedFrame].label}`" :style="{ backgroundImage: `url(${previewUrl})`, backgroundPosition: mascotFrames[selectedFrame].position }" /></div>
      <div class="mascot-frames" role="group" aria-label="六个表情"><button v-for="(frame, index) in mascotFrames" :key="frame.label" type="button" :aria-pressed="selectedFrame === index" @click="selectedFrame = index"><span :style="{ backgroundImage: `url(${previewUrl})`, backgroundPosition: frame.position }" aria-hidden="true" /><small>{{ frame.label }}</small></button></div>
      <p class="mascot-hint">检查角色是否一致、边缘是否完整。应用后同步更新首页和项目对话中的 Agent 头像，互动表情和减少动画设置继续生效。</p>
      <div class="mascot-actions"><button type="button" class="primary-button" :disabled="saving || loading || !!applied" @click="mascot.apply(preview!.id)"><Check :size="16" />{{ applied ? '已应用此形象' : '应用此形象' }}</button><a class="ghost-button" :href="previewUrl" target="_blank" rel="noopener noreferrer"><Download :size="15" />查看完整图集</a></div>
      <p v-if="applied" class="mascot-hint" role="status"><i class="mascot-status is-ready" />首页和项目对话正在使用这个形象。</p>
    </div>
  </section>
</template>

<style scoped>
.mascot-settings { display:grid; gap:12px; margin-top:32px; padding-top:28px; border-top:1px solid var(--theme-border); }
.mascot-settings header,.mascot-preview-heading,.mascot-actions,.mascot-hint { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }
.mascot-settings header { align-items:flex-start; }
.mascot-settings h3 { margin:0; color:var(--theme-text); font-size:var(--ui-font-section); line-height:var(--ui-line-heading); }
.mascot-settings header p { margin:7px 0 8px; font-size:var(--ui-font-caption); color:var(--theme-text-muted); line-height:1.7; }
.mascot-badge { padding:5px 10px; border-radius:999px; background:var(--theme-surface); color:var(--theme-text-muted); font-size:var(--ui-font-caption); }
.mascot-presets { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.mascot-preset { display:flex; flex-direction:column; align-items:center; min-width:0; padding:12px 8px 14px; border:1px solid var(--theme-border); border-radius:var(--ui-radius-card); background:var(--theme-surface); color:var(--theme-text); text-align:center; cursor:pointer; }
.mascot-preset:hover { background:var(--theme-surface-hover); border-color:var(--theme-border-strong); }
.mascot-preset[aria-pressed=true] { border-color:var(--theme-text-muted); background:var(--theme-surface-hover); box-shadow:inset 0 0 0 1px var(--theme-text-muted); }
.mascot-preset:focus-visible { outline:2px solid var(--theme-text-muted); outline-offset:3px; }
.mascot-preset:disabled { cursor:wait; opacity:.6; }
.mascot-preset-art { display:block; width:min(100%,112px); aspect-ratio:1; margin-bottom:8px; background-size:300% 200%; background-position:0% 0%; background-repeat:no-repeat; }
.mascot-preset-name { display:flex; align-items:center; justify-content:center; gap:5px; min-height:22px; font-size:var(--ui-font-control); }
.mascot-preset-name strong { font-weight:600; }.mascot-preset small { margin-top:4px; color:var(--theme-text-muted); font-size:var(--ui-font-caption); line-height:1.5; }
.mascot-custom-title { margin:14px 0 0; padding-top:22px; border-top:1px solid var(--theme-border); color:var(--theme-text); font-size:var(--ui-font-card); font-weight:600; }
.mascot-label { font-size:var(--ui-font-control); color:var(--theme-text); }
.mascot-settings textarea,.mascot-settings select { box-sizing:border-box; width:100%; min-width:0; padding:12px; border:1px solid var(--theme-input-border); border-radius:var(--ui-radius-control); background:var(--theme-input); color:var(--theme-text); font:inherit; font-size:var(--ui-font-control); line-height:1.7; }
.mascot-settings textarea { min-height:118px; resize:vertical; }
.mascot-settings select { min-height:var(--ui-control-height); }
.mascot-hint { margin:0; justify-content:flex-start; color:var(--theme-text-muted); font-size:var(--ui-font-caption); line-height:1.7; }
.mascot-hint > span:last-child { margin-left:auto; }
.mascot-actions { justify-content:flex-start; }
.mascot-error { margin:0; color:var(--theme-text); font-size:var(--ui-font-caption); line-height:1.7; overflow-wrap:anywhere; }
.mascot-status { display:inline-block; width:7px; height:7px; margin-right:3px; border-radius:50%; flex-shrink:0; }
.is-pending { background:var(--theme-status-yellow); }.is-failed { background:var(--theme-status-red); }.is-ready { background:var(--theme-status-green); }
.mascot-preview { display:grid; gap:14px; margin-top:8px; padding:18px; border:1px solid var(--theme-border); border-radius:var(--ui-radius-card); background:var(--theme-surface); }
.mascot-preview-heading strong { font-size:var(--ui-font-card); }
.mascot-preview-themes { display:flex; gap:4px; }
.mascot-preview-themes button { min-height:32px; padding:5px 10px; border:1px solid transparent; border-radius:8px; background:transparent; color:var(--theme-text-muted); font:inherit; font-size:var(--ui-font-caption); }
.mascot-preview-themes button[aria-pressed=true] { border-color:var(--theme-border-strong); background:var(--theme-surface-hover); color:var(--theme-text); }
.mascot-stage { display:grid; place-items:center; min-height:206px; border-radius:var(--ui-radius-control); background-size:20px 20px; }
.mascot-stage.dark { background-color:#181818; background-image:linear-gradient(#ffffff08 1px,transparent 1px),linear-gradient(90deg,#ffffff08 1px,transparent 1px); }
.mascot-stage.light { background-color:#f2f1ed; background-image:linear-gradient(#00000009 1px,transparent 1px),linear-gradient(90deg,#00000009 1px,transparent 1px); }
.mascot-stage > span { width:176px; height:176px; }
.mascot-stage > span,.mascot-frames button > span { display:block; background-size:300% 200%; background-repeat:no-repeat; }
.mascot-frames { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:6px; }
.mascot-frames button { display:grid; justify-items:center; gap:5px; min-width:0; padding:8px 3px; border:1px solid transparent; border-radius:var(--ui-radius-control); color:var(--theme-text-muted); background:transparent; cursor:pointer; }
.mascot-frames button[aria-pressed=true] { border-color:var(--theme-border-strong); background:var(--theme-surface-hover); color:var(--theme-text); }
.mascot-frames button > span { width:min(100%,64px); aspect-ratio:1; }.mascot-frames small { font-size:var(--ui-font-caption); }
.mascot-spinner { animation:mascot-spin 1.2s linear infinite; }@keyframes mascot-spin { to { transform:rotate(360deg); } }
[data-reduce-animations=true] .mascot-spinner { animation:none; }
@media(max-width:600px) { .mascot-presets { grid-template-columns:repeat(2,minmax(0,1fr)); }.mascot-preview { padding:12px; }.mascot-frames { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@media(prefers-reduced-motion:reduce) { .mascot-spinner { animation:none; } }
</style>
