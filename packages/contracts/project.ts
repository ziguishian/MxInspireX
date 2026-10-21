export type ProjectStatus =
  | 'draft'
  | 'discovery'
  | 'strategy'
  | 'concept'
  | 'design'
  | 'engineering'
  | 'commercial'
  | 'export'
  | 'archived';

export interface Project {
  id: string;
  name: string;
  slug: string;
  brief: string;
  budgetMinor: number | null;
  currency: string;
  status: ProjectStatus;
  rootPath: string;
  createdAt: string;
  updatedAt: string;
  titleMode?: 'auto' | 'manual';
  titleGeneratedAt?: string | null;
  titlePending?: boolean;
  latestTaskId?: string | null;
  latestTaskStatus?: 'empty' | 'queued' | 'running' | 'succeeded' | 'awaiting_input' | 'failed' | 'cancelled';
  summary?: string;
  activityAt?: string | null;
  previewRevision?: string;
}

export interface ProjectCreateInput {
  name: string;
  brief: string;
  budgetMinor: number | null;
  currency: string;
}
