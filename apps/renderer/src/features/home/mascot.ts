import { computed, inject, ref, type CSSProperties, type InjectionKey } from 'vue';

export type MascotGeneration = { id: string; prompt: string; status: 'queued' | 'running' | 'succeeded' | 'failed'; model: string; imageUrl: string | null; error: string };
export type MascotSettings = { active: MascotGeneration | null; activePreset?: MascotPresetId | null; latest: MascotGeneration | null };
export type MascotProvider = { key: string; baseUrl?: string; model?: string; manual?: boolean };
export const mascotPresets = [
  { id:'robot', name:'点阵机器人', description:'熟悉的设计搭档', image:'mascots/robot-soft.png', positions:['1.26953125% 2.734375%','50.146484375% 2.734375%','98.681640625% 2.734375%','1.26953125% 97.8515625%','50.09765625% 97.65625%','98.681640625% 97.8515625%'] },
  // Registered viewport offsets keep generated cutouts centered on a common foot baseline without altering the artwork.
  { id:'cream-cat', name:'奶油猫', description:'陪灵感慢慢长大', image:'mascots/cream-cat.png', positions:['3.857421875% -0.5859375%','50.244140625% -0.390625%','96.142578125% -0.5859375%','3.857421875% 93.9453125%','50.146484375% 93.9453125%','96.630859375% 93.9453125%'] },
  { id:'cloud', name:'云朵', description:'让想法轻盈一点', image:'mascots/cloud.png', positions:['0.9765625% -1.3671875%','50.048828125% -1.3671875%','98.095703125% -1.3671875%','0.9765625% 92.7734375%','50.048828125% 92.7734375%','98.095703125% 92.7734375%'] },
  { id:'sprout', name:'小芽', description:'每个念头都有新生', image:'mascots/sprout.png', positions:['1.904296875% 1.171875%','50.29296875% 1.3671875%','100.048828125% 1.3671875%','1.904296875% 100.1953125%','50.146484375% 100.1953125%','100.1953125% 100.390625%'] },
  { id:'moon-bunny', name:'月团', description:'把温柔装进灵感', image:'mascots/moon-bunny.png', positions:['0% 0%','50% 0%','100% 0%','0% 100%','50% 100%','100% 100%'] },
  { id:'amber-fox', name:'暖栗', description:'为每个点子添点暖意', image:'mascots/amber-fox.png', positions:['0% 0%','50% 0%','100% 0%','0% 100%','50% 100%','100% 100%'] },
  { id:'sea-otter', name:'汐团', description:'拾起灵感的小贝壳', image:'mascots/sea-otter.png', positions:['0% 0%','50% 0%','100% 0%','0% 100%','50% 100%','100% 100%'] },
  { id:'star-penguin', name:'星眠', description:'陪你收藏闪亮想法', image:'mascots/star-penguin.png', positions:['0% 0%','50% 0%','100% 0%','0% 100%','50% 100%','100% 100%'] },
] as const;
export type MascotPresetId = typeof mascotPresets[number]['id'];
export function mascotPresetImageUrl(id: MascotPresetId) {
  const preset = mascotPresets.find(item => item.id === id);
  return preset ? `${import.meta.env.BASE_URL}assets/${preset.image}` : '';
}
export const mascotFrames = [
  { label: '待机', position: '0% 0%' }, { label: '思考', position: '50% 0%' }, { label: '开心', position: '100% 0%' },
  { label: '眨眼', position: '0% 100%' }, { label: '等待', position: '50% 100%' }, { label: '困倦', position: '100% 100%' },
];

export function mascotImageUrl(baseUrl: string, item: MascotGeneration | null) {
  return item?.imageUrl && /^\/api\/mascot\/generations\/[a-f0-9-]+\/image$/.test(item.imageUrl) ? `${baseUrl}${item.imageUrl}` : '';
}

export function mascotSpriteStyle(baseUrl: string, item: MascotGeneration | null, presetId: MascotPresetId | null = 'robot'): CSSProperties {
  const url = mascotImageUrl(baseUrl, item) || (presetId ? mascotPresetImageUrl(presetId) : '');
  const frames = !item && presetId ? mascotPresets.find(preset => preset.id === presetId)?.positions : null;
  const positions = frames || mascotFrames.map(frame => frame.position);
  return url ? {
    '--xiaoju-image': `url("${url}")`, filter: 'none',
    '--xiaoju-frame-idle': positions[0], '--xiaoju-frame-thinking': positions[1], '--xiaoju-frame-happy': positions[2],
    '--xiaoju-frame-wink': positions[3], '--xiaoju-frame-calm': positions[4],
    '--xiaoju-frame-blink': positions[5], '--xiaoju-frame-sleepy': positions[5],
  } : {};
}

export function createMascotSettings(apiBaseUrl: string) {
  const active = ref<MascotGeneration | null>(null);
  const activePreset = ref<MascotPresetId | null>('robot');
  const activeName = computed(() => active.value ? '自定义形象' : mascotPresets.find(preset => preset.id === activePreset.value)?.name || '点阵机器人');
  const latest = ref<MascotGeneration | null>(null);
  const loading = ref(false);
  const saving = ref(false);
  const error = ref('');
  const uncertain = ref(false);
  const ready = ref(false);
  const running = computed(() => latest.value?.status === 'queued' || latest.value?.status === 'running');
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;

  function update(data: MascotSettings) {
    active.value = data.active;
    activePreset.value = data.active ? null : mascotPresets.find(item => item.id === data.activePreset)?.id ?? 'robot';
    latest.value = data.latest;
  }

  async function request<T>(path = '', init?: RequestInit): Promise<T> {
    const response = await fetch(`${apiBaseUrl}/api/mascot${path}`, { ...init, headers: { 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(20000) });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(typeof data?.detail === 'string' ? data.detail : '吉祥物设置暂不可用，请检查本地服务。');
    }
    return response.json();
  }

  function schedule() {
    clearTimeout(timer);
    if (!disposed && (running.value || uncertain.value)) timer = setTimeout(() => { void load(); }, 2500);
  }

  async function load() {
    if (loading.value || saving.value || disposed) return;
    loading.value = true;
    try {
      const data = await request<MascotSettings>();
      if (disposed) return;
      update(data);
      error.value = '';
      uncertain.value = false;
      ready.value = true;
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '无法读取吉祥物设置。';
    } finally {
      loading.value = false;
      schedule();
    }
  }

  async function generate(prompt: string, provider: MascotProvider, model: string) {
    if (loading.value || saving.value || running.value || uncertain.value || !ready.value) return;
    clearTimeout(timer);
    saving.value = true;
    error.value = '';
    try {
      latest.value = await request<MascotGeneration>('/generations', { method: 'POST', body: JSON.stringify({
        requestId: crypto.randomUUID(), prompt: prompt.trim(), provider: { key: provider.key, baseUrl: provider.baseUrl || '' },
        model: model || (provider.manual ? provider.model || '' : ''),
      }) });
    } catch (reason) {
      uncertain.value = true;
      error.value = `${reason instanceof Error ? reason.message : '无法确认生成状态。'} 正在核对结果，请勿重复生成。`;
    } finally {
      saving.value = false;
      schedule();
    }
  }

  async function saveSelection(selection: { generationId: string | null } | { presetId: MascotPresetId }) {
    if (loading.value || saving.value || !ready.value) return;
    clearTimeout(timer);
    saving.value = true;
    error.value = '';
    try {
      const data = await request<MascotSettings>('', { method: 'PUT', body: JSON.stringify(selection) });
      if (!disposed) update(data);
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '应用失败，请重试。';
    } finally { saving.value = false; schedule(); }
  }

  const apply = (identity: string | null) => saveSelection({ generationId:identity });
  const applyPreset = (presetId: MascotPresetId) => saveSelection({ presetId });

  return { active, activePreset, activeName, latest, loading, saving, ready, running, uncertain, error, load, generate, apply, applyPreset, apiBaseUrl,
    dispose() { disposed = true; clearTimeout(timer); } };
}

export type MascotSettingsController = ReturnType<typeof createMascotSettings>;
export const mascotSettingsKey: InjectionKey<MascotSettingsController> = Symbol.for('mxinspirex:mascot-settings');
export const useMascotSettings = () => inject(mascotSettingsKey, null);
