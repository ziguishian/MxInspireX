export type ConversationMemoryRecord = {
  id: string; key: string; version: number; content: string;
  category: 'preference' | 'fact' | 'asset' | 'decision' | 'progress';
  scope: 'conversation' | 'topic' | 'task'; topic: string;
  status: 'confirmed' | 'assumed' | 'proposed' | 'observed'; active: boolean;
  source: { taskId: string; quote?: string; assetId?: string };
  assetId?: string; sha256?: string; role?: 'input' | 'logo' | 'key_visual' | 'specialist' | 'style' | 'artifact';
};
export type ImageReferenceSnapshot = {
  id: string; taskId: string; deliverableId: string;
  bindingPolicy?: 'candidates';
  references: Array<{ assetId: string; sha256: string; role: string; purpose: string; memoryId?: string; memoryVersion?: number }>;
  analysis?: {
    images: Array<{ asset_id: string; mode: 'inspiration' | 'identity' | 'edit' | 'layout'; visual_prompt: string; use: string; avoid?: string; preserve?: string }>;
    synthesis: string;
  };
  providerInputAssetIds?: string[];
  resolution?: {
    references: Array<{ assetId: string; sha256: string; mode?: string | null; origins: string[] }>;
    nodeVersions: Record<string, string>;
    output: { mode: 'create'; nodeId: string | null };
    binding: { scopeId?: string; itemIds?: string[]; revision?: number };
    pendingDependencies: string[];
    referenceSelectionId?: string | null;
    providerInputAssetIds?: string[];
  };
};
export type ImageQuality = {
  model: string; tier: 'draft' | 'standard' | 'final'; requestedQuality: string;
  status: 'applied' | 'unsupported'; quality?: string; inputFidelity?: string; notice?: string;
};
export type ImageRoute = {
  mode: 'auto' | 'manual'; tier: 'draft' | 'standard' | 'final'; primaryModel: string; finalModel: string;
  fallbackUsed: boolean; candidates: Array<{ model: string; status: 'planned' | 'submitted' | 'safe_rejected' | 'succeeded' | 'unknown'; reason?: string }>;
  parameterAdjustments?: string[];
};
export type ConversationMemorySnapshot = {
  sessionId: string; memoryRevision: number; analyzed: boolean; topic: string;
  selected: ConversationMemoryRecord[]; referenceSnapshots: ImageReferenceSnapshot[];
  progress?: Array<{ nodeId: string; title: string; assetId?: string; status: string; imageQuality?: ImageQuality; imageRoute?: ImageRoute;
    dimensions?: { width?: number; height?: number }; referenceSnapshot?: ImageReferenceSnapshot }>;
};
