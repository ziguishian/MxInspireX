<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { editableModelPrice, formatModelPrice } from '../modelEconomy';
const props = defineProps<{ apiBaseUrl: string }>();
type Quote = { provider: string; baseUrl: string; model: string; kinds: string[]; price: Record<string, unknown> };
const quotes = ref<Quote[]>([]);
const kinds = [{ id:'text', label:'文本' }, { id:'image', label:'图像' }, { id:'video', label:'视频' }, { id:'audio', label:'音频' }, { id:'search', label:'联网搜索' }, { id:'embedding', label:'知识检索' }, { id:'3d', label:'3D' }];
const selectedKind = ref('text');
const selectedKey = ref('');
const key = (q: Quote) => JSON.stringify([q.provider, q.baseUrl, q.model]);
const host = (q: Quote) => { try { return new URL(q.baseUrl).host; } catch { return q.baseUrl || '本地服务'; } };
const options = computed(() => quotes.value.filter(q => q.kinds.includes(selectedKind.value === 'search' ? 'text' : selectedKind.value)));
const selected = computed(() => options.value.find(q => key(q) === selectedKey.value));
const editing = ref(false), saving = ref(false), message = ref('');
const draft = ref<Record<string, unknown>>({});
const fields = [
  ['inputPerMillion','输入 / 百万 Token'], ['outputPerMillion','输出 / 百万 Token'], ['cachedPerMillion','缓存读取 / 百万 Token'], ['cacheWritePerMillion','缓存写入 / 百万 Token'],
  ['imageInputPerMillion','图像输入 / 百万 Token'], ['imageOutputPerMillion','图像输出 / 百万 Token'], ['perInputImage','每张参考图'], ['perImage','每张生成图'], ['perSecond','每秒'], ['perRequest','每次请求'], ['perSearch','每次搜索'],
  ['audioInputPerMillion','音频输入 / 百万 Token'], ['audioOutputPerMillion','音频输出 / 百万 Token'], ['videoInputPerMillion','视频输入 / 百万 Token'], ['videoOutputPerMillion','视频输出 / 百万 Token'],
];
watch(options, value => { if (!value.some(q => key(q) === selectedKey.value)) selectedKey.value = value[0] ? key(value[0]) : ''; editing.value = false; });
watch(selectedKey, () => { editing.value = false; message.value = ''; });
async function load() {
  try { const r = await fetch(`${props.apiBaseUrl}/api/credits/prices`); if (!r.ok) throw new Error('报价目录暂时不可用'); quotes.value = await r.json(); }
  catch (error) { message.value = error instanceof Error ? error.message : '读取失败'; }
}
function edit() { draft.value = editableModelPrice(selected.value?.price); editing.value = true; message.value = ''; }
async function save() {
  if (!selected.value || saving.value) return;
  saving.value = true; message.value = '';
  try {
    const price = Object.fromEntries(Object.entries(draft.value).filter(([, value]) => value !== '' && value != null));
    if (Object.keys(price).length < 2) throw new Error('请填写至少一项实际单价；留空表示未知，0 表示免费。');
    const response = await fetch(`${props.apiBaseUrl}/api/credits/prices`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...selected.value, kinds:undefined, price})});
    if (!response.ok) throw new Error('报价保存失败，请检查数值与服务地址');
    await load(); editing.value = false; message.value = '报价已保存，用于后续请求；历史账单保持原始价格。';
    window.dispatchEvent(new Event('model-prices-changed'));
  } catch (error) { message.value = error instanceof Error ? error.message : '保存失败'; }
  finally { saving.value = false; }
}
onMounted(load);
</script>
<template>
  <section class="credit-pricing" aria-label="分类估价与模型单价">
    <header><h3>分类估价</h3><small>参考单价 × 实际用量；不代表预扣费或服务商账单</small></header>
    <div class="credit-price-tabs" role="group" aria-label="计费类别"><button v-for="kind in kinds" :key="kind.id" :aria-pressed="selectedKind === kind.id" @click="selectedKind = kind.id">{{ kind.label }}</button></div>
    <label>模型与服务<select v-model="selectedKey" aria-label="估价模型"><option v-if="!options.length" value="">当前未配置此类模型</option><option v-for="q in options" :key="key(q)" :value="key(q)">{{ q.model }} · {{ q.provider }} · {{ host(q) }}</option></select></label>
    <div v-if="selected" class="credit-quote"><strong>{{ formatModelPrice(selected.price) }}</strong><small>{{ selected.price.source === 'manual' ? '你填写的服务报价' : selected.price.source === 'gateway' ? '来自当前服务模型目录' : selected.price.source === 'default' ? '公开参考价格，实际结算可能不同' : '服务未返回单价；请同步完整价格目录或填写当前服务报价。' }}</small><small v-if="selectedKind === 'search'">搜索工具附加费与文本用量分别计算；缺少搜索单价时不能估算完整搜索费用。</small><small v-if="selected.price.checkedAt">价格核对日期：{{ selected.price.checkedAt }}</small><button class="ghost-button" type="button" @click="edit">{{ editing ? '重新读取报价' : '填写服务报价' }}</button></div>
    <form v-if="editing && selected" class="credit-price-editor" @submit.prevent="save">
      <p>填写服务商实际费率。留空表示未知，0 表示明确免费；不会修改服务商账户或余额。</p>
      <label>计价币种<select v-model="draft.currency"><option>CNY</option><option>USD</option></select></label>
      <div class="credit-price-fields"><label v-for="[field, label] in fields" :key="field">{{ label }}<input v-model.number="draft[field]" type="number" min="0" step="any" placeholder="未提供" /></label></div>
      <div><button type="submit" class="primary-button" :disabled="saving">{{ saving ? '保存中…' : '保存报价' }}</button><button type="button" class="ghost-button" @click="editing = false">取消</button></div>
    </form>
    <p v-if="message" role="status">{{ message }}</p>
  </section>
</template>
<style scoped>
.credit-pricing { display:grid; gap:14px; border-top:1px solid var(--theme-border); padding-top:20px; }
header h3 { margin:0 0 4px; font-size:var(--ui-font-section); }
small,p { color:var(--theme-text-muted); font-size:var(--ui-font-caption); }
.credit-price-tabs { display:flex; flex-wrap:wrap; gap:6px; }
.credit-price-tabs button { padding:7px 10px; border:1px solid var(--theme-border); border-radius:8px; color:var(--theme-text-muted); background:transparent; font:inherit; cursor:pointer; }
.credit-price-tabs button[aria-pressed="true"] { background:var(--theme-surface-hover); color:var(--theme-text); border-color:var(--theme-border-strong); }
label { display:grid; gap:6px; min-width:0; font-size:var(--ui-font-control); }
.credit-quote { display:grid; gap:8px; padding:14px; border-radius:var(--ui-radius-card); background:var(--theme-surface); overflow-wrap:anywhere; }
.credit-quote strong { font-size:var(--ui-font-control); line-height:1.8; font-weight:500; }
.credit-quote button { justify-self:start; }
.credit-price-editor { display:grid; gap:12px; }
.credit-price-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.credit-price-editor button + button { margin-left:8px; }
@media(max-width:600px) { .credit-price-fields { grid-template-columns:1fr; } }
</style>
