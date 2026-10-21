import type { DeliveryFinding } from './deliveryFindings';
export type DeliveryProgress = {
  id: string; title: string; kind: string;
  status: 'pending' | 'generating' | 'blocked' | 'ready' | 'passed' | 'needs_review';
  nodeIds?: string[]; blockingFields?: string[]; issue?: string;
  artifacts?: Array<{ nodeId: string; assetId?: string; fingerprint: string }>;
  findings?: DeliveryFinding[];
};

export type DesignBatch = {
  version: number;
  intent: 'initial' | 'resume' | 'next_batch' | 'revise';
  status: 'needs_plan' | 'ready';
  number: number;
  itemIds: string[];
  previousItemIds: string[];
  currentProgress: DeliveryProgress[];
  sourceTaskId?: string;
  suggestedNext?: string[];
};
