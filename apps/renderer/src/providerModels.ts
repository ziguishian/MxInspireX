import { computed, shallowRef } from 'vue';
import { localServiceHint, taskIssue } from './features/taskErrors';

export type DetectedModel = {
  id: string;
  name?: string;
  ownedBy?: string | null;
  vendor?: string | null;
  kind?: string;
  kinds?: string[];
  modality?: string | null;
  inputModalities?: string[];
  outputModalities?: string[];
  supportedParameters?: string[];
  contextLength?: number | null;
  description?: string | null;
  created?: number | null;
  pricing?: Record<string, unknown> | null;
  price?: Record<string, unknown>;
  category?: string | string[] | null;
  providerCategory?: string | string[] | null;
  catalogSource?: string | null;
  classificationSource?: string | null;
  classificationConfidence?: string | null;
};
export type ModelCatalogResponse = {
  models: string[];
  savedAt?: string | null;
  source?: string;
  unavailableModels?: string[];
  modelCatalog?: DetectedModel[];
  textModels?: string[];
  imageModels?: string[];
  videoModels?: string[];
  threeDModels?: string[];
  audioModels?: string[];
  unknownModels?: string[];
  catalogCoverage?: 'standard' | 'partial' | 'complete';
  catalogSources?: string[];
  catalogWarnings?: string[];
  routeAvailability?: {
    autoReady: boolean;
    missingTiers: string[];
    tiers: Record<string, {
      available: boolean;
      configuredModel: string;
      resolvedModel?: string | null;
      provider?: string;
      baseUrl?: string;
      inputModalities?: string[];
      reason?: string | null;
    }>;
  };
};
export type ModelCatalogSource = {
  provider: string;
  baseUrl: string;
  secret?: string;
  saveCredential?: boolean;
  catalogSecret?: string;
  saveCatalogCredential?: boolean;
};

export function selectAvailableModel(preferred: string, options: string[]): string {
  return options.includes(preferred) ? preferred : options[0] || '';
}

/** Only IDs returned by this request may become selectable model options. */
export function normalizeModelResponse(response: ModelCatalogResponse) {
  if (!Array.isArray(response.models)) throw new Error('模型接口未返回有效的模型列表');
  const models = [...new Set(response.models.filter((id) => typeof id === 'string' && id.trim()).map((id) => id.trim()))];
  const catalog = models.map((id) => response.modelCatalog?.find((item) => item.id === id) || { id });
  const options = (ids: string[] | undefined, kind: string) => {
    // An explicitly empty capability list must stay empty.
    const candidates = ids ?? catalog.filter((item) => item.kinds?.includes(kind) || item.kind === kind
      || (kind === 'text' && !item.kind && !item.kinds?.length)).map((item) => item.id);
    return models.filter((id) => candidates.includes(id));
  };
  return { models, catalog, unavailable: response.unavailableModels || [], text: options(response.textModels, 'text'), image: options(response.imageModels, 'image'),
    video: options(response.videoModels, 'video'), audio: options(response.audioModels, 'audio'), threeD: options(response.threeDModels, '3d'),
    unknown: options(response.unknownModels, 'unknown'),
    coverage: response.catalogCoverage || 'standard', sources: response.catalogSources || [], warnings: response.catalogWarnings || [],
    routeAvailability: response.routeAvailability };
}

/** One shared live catalog; changing gateways invalidates in-flight responses. */
export function createProviderModelCatalog(fetchModels: (source: ModelCatalogSource, signal: AbortSignal) => Promise<ModelCatalogResponse>) {
  const empty = () => normalizeModelResponse({ models: [] });
  const data = shallowRef(empty());
  const status = shallowRef<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const error = shallowRef('');
  const savedAt = shallowRef<string | null>(null);
  let controller: AbortController | undefined;
  let sequence = 0;
  let catalogSource = '';
  const sourceKey = (source: Pick<ModelCatalogSource, 'provider' | 'baseUrl'>) => `${source.provider}:${source.baseUrl.trim().replace(/\/+$/, '')}`;

  function reset() {
    sequence += 1;
    controller?.abort();
    controller = undefined;
    data.value = empty();
    status.value = 'idle';
    error.value = '';
    savedAt.value = null;
    catalogSource = '';
  }

  function hydrate(response: ModelCatalogResponse, source?: Pick<ModelCatalogSource, 'provider' | 'baseUrl'>) {
    reset();
    data.value = normalizeModelResponse(response);
    savedAt.value = response.savedAt || null;
    status.value = response.savedAt || response.models.length ? 'ready' : 'idle';
    catalogSource = source ? sourceKey(source) : '';
  }

  async function refresh(source: ModelCatalogSource): Promise<boolean> {
    const cached = catalogSource === sourceKey(source) ? { data: data.value, savedAt: savedAt.value } : undefined;
    reset();
    catalogSource = sourceKey(source);
    const requestSequence = sequence;
    const currentController = new AbortController();
    controller = currentController;
    status.value = 'loading';
    const timeout = setTimeout(() => currentController.abort(), 45_000);
    try {
      const response = await fetchModels(source, currentController.signal);
      if (requestSequence !== sequence) return false;
      if (currentController.signal.aborted) throw new Error('模型列表读取超时，请重试');
      data.value = normalizeModelResponse(response);
      savedAt.value = response.savedAt || new Date().toISOString();
      status.value = 'ready';
      return true;
    } catch (cause) {
      if (requestSequence !== sequence) return false;
      // A renderer fetch failure means the local API is unreachable. Upstream
      // transport failures arrive as API responses (regular Errors).
      const reason = currentController.signal.aborted ? '模型列表读取超时'
        : cause instanceof TypeError ? localServiceHint : cause;
      const issue = taskIssue(reason);
      error.value = issue.code === 'unknown' ? (cause instanceof Error ? cause.message : '暂时无法读取模型目录，请稍后重试。') : issue.message;
      if (cached && ['network', 'local_service'].includes(issue.code)) {
        data.value = cached.data;
        savedAt.value = cached.savedAt;
      }
      status.value = 'error';
      return false;
    } finally {
      clearTimeout(timeout);
      if (requestSequence === sequence) controller = undefined;
    }
  }

  return { data, status, error, savedAt, hydrate, loading: computed(() => status.value === 'loading'), reset, refresh };
}
