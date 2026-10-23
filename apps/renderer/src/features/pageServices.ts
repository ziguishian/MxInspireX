import type { ReferenceSelection, ReferenceSubmission } from './references';
import { inject, type InjectionKey, type Ref } from 'vue';
import type { Clarification, ClarificationSubmission } from './clarification';
import type { Project } from '../../../../packages/contracts/project';
import type { Board } from '../canvasEditing';
import type { DesignStep } from '../designPresentation';
import type { ExecutionInfo } from './taskProgress';
import type { TaskIssue } from './taskErrors';
import type { MessageReference, TaskReferenceSnapshot } from './composer/messageReferences';

type Value<T> = Readonly<Ref<T>>;
export type LibraryAsset = { id: string; kind: string; pathRelative: string; byteSize: number; mime?: string; projectId?: string; projectName?: string; htmlNodeId?: string; revision?: string; createdAt?: string; updatedAt?: string };
export type KnowledgeDocument = { id: string; title: string; pathRelative: string; status: string; parser?: string; warning?: string | null; chunkCount?: number; parserVersion?: number; pageCount?: number; imageCount?: number; partCount?: number };
export type CanvasDocument = { schemaVersion?: string; nodes: Record<string, any>[]; edges: Record<string, any>[] };
export type MessageResubmission = { taskId: string; text: string };
export type ConversationMessage = { conversationTurnId?: string; referenceSelection?: ReferenceSelection; referenceSnapshot?: TaskReferenceSnapshot; references?: MessageReference[]; animateReply?: boolean; verification?: { technical: string; content: string }; execution?: ExecutionInfo; issue?: TaskIssue; sources?: { url: string; title: string }[]; role: 'user' | 'assistant'; content: string; taskId?: string; error?: boolean; steps?: DesignStep[]; status?: string; clarification?: Clarification };
// Contexts are provided by the mounted app, never by a process-global store.
// Pages receive only the data and commands for their own domain. Their search,
// pagination, forms and DOM refs remain inside the page/component lifecycle.
function context<T>(name: string) {
  // Keep the identifier stable when Vite reloads a page and its provider at
  // different times. Only the identifier is shared; values stay in Vue's tree.
  const key: InjectionKey<T> = Symbol.for(`langju:page-services:${name}`);
  const use = () => { const value = inject(key); if (!value) throw new Error(`Missing page services: ${name}`); return value; };
  return { key, use };
}
export const homeServices = context<{
  greetingCopy: Value<string>; errorMessage: Value<string>;
  isSubmitting: Value<boolean>; addFiles: (files: File[]) => void;
  composerReady: () => void;
  useExample: (prompt: string) => void; startDemo?: (caseId: string) => void;
  /** Imported product cases appear only after their reviewed images exist. */
  showcaseSlugs?: Value<string[]>;
  /** Opens a saved curated project through its display-only staged playback. */
  openFeaturedProject?: (slug: string) => void;
}>('home');
export const projectLibraryServices = context<{
  projects: Value<Project[]>; isLoading: Value<boolean>; errorMessage: Value<string>; apiBaseUrl: string;
  projectCanvasPreviews: Value<Record<string, CanvasDocument>>;
  loadPreview: (project: Project) => Promise<void>;
  selectProject: (id: string) => void; createBlankCanvas: () => Promise<void>;
  renameProject: (project: Project, name: string) => Promise<void>;
  requestDeleteProject: (project: Project) => void;
}>('project-library');
export type LibraryLoadState = { loading: Value<boolean>; error: Value<string>; retry: () => void };
export const assetLibraryServices = context<{
  loadState: LibraryLoadState;
  globalAssets: Value<LibraryAsset[]>; apiBaseUrl: string;
  requestDeleteAsset: (asset: LibraryAsset) => void;
  assetDisplayName: (asset: LibraryAsset) => string;
  openProject?: (id: string) => void;
}>('asset-library');
export const knowledgeLibraryServices = context<{
  loadState: LibraryLoadState;
  apiBaseUrl: string;
  globalKnowledgeDocs: Value<KnowledgeDocument[]>; isUploadingGlobalKnowledge: Value<boolean>;
  isReindexingGlobalKnowledge: Value<boolean>; uploadGlobalKnowledge: (event: Event) => Promise<void>;
  reindexGlobalKnowledge: () => Promise<void>;
  deleteDocument: (document: KnowledgeDocument) => void;
}>('knowledge-library');
export const helpServices = context<{ appVersion: string }>('help');
export type SettingsSection = 'account' | 'general' | 'text' | 'routing' | 'appearance' | 'components' | 'about' | 'help';
export const settingsServices = context<{
  current: Value<SettingsSection>;
  tabs: readonly { key: SettingsSection; label: string }[];
  select: (section: SettingsSection) => void; close: () => void;
  ready: (mounted: boolean) => void;
}>('settings');
export const accountServices = context<{
  userNickname: Ref<string>; userBio: Ref<string>; userAvatarIndex: Ref<number>;
  activeAvatarOption: Value<{ position: string }>; userAvatarOptions: readonly { index: number; label: string; position: string }[];
  userProfileSaving: Value<boolean>; saveUserProfile: () => void; closeUserCenter: () => void;
  monthlyTokenTotal: Value<number>; weeklyTokenTotal: Value<number>;
  monthlyTokenHeatmap: Value<{ key: string; day: number | null; value: number; level: number; label: string }[]>;
  weeklyTokenUsage: Value<{ key: string; value: number; height: number; weekday: string; label: string }[]>;
  formatTokenUsage: (value: number) => string; creditPending: Value<number>; creditLoadError: Value<string>;
}>('account');
export type ScheduleOptions = { apiBaseUrl: string; projects: { id: string; name: string }[]; provider?: { key: string; baseUrl: string; model: string }; imageModel?: string; allowExternalNetwork: boolean };
export const scheduleServices = context<{
  options: Value<ScheduleOptions>; openProject: (id: string) => void;
  openSettings: () => void; changed: () => void;
}>('schedules');
export type CanvasOptions = { runWorkflowNode?: (kind: any, prompt: string, position: {x:number;y:number}, params: Record<string, any>) => Promise<boolean | undefined>; demoMode?: boolean; messageEditRequest?: { taskId: string; requestId: number }; resendMessage: (submission: MessageResubmission) => Promise<boolean>; taskFocus?: { taskId: string; nodeId?: string; requestId: number }; messages: ConversationMessage[]; busy: boolean; progress: string; error: string; apiBaseUrl: string; projectId: string; canvasDocument: CanvasDocument; modelOptions: string[]; textModelOptions: string[]; audioModelOptions: string[]; videoModelOptions: string[] };
export const projectWorkspaceServices = context<{
  isLoading: Value<boolean>; errorMessage: Value<string>;
  options: Value<CanvasOptions | null>; designCanvasVisible: Ref<boolean>;
  events: {
    'return-home': () => void;
    'task-action': (taskId: string, action: TaskIssue['action']) => void;
    reference: (value: string, tentative?: boolean) => void;
    'cancel-canvas-reference': () => void;
    'move-node': (id: string, position: { x: number; y: number }) => void;
    'generate-node': (kind: 'image' | 'video' | 'audio' | 'text' | 'html' | 'cad' | 'upload', prompt: string, position: { x: number; y: number }, params: Record<string, any>) => void;
    'cancel-node-task': (nodeId: string, taskId: string) => void;
    'canvas-error': (message: string) => void; 'canvas-change': (document: Board) => void;
    'select-reference': (submission: ReferenceSubmission) => void;
    'composer-ready': () => void; clarify: (submission: ClarificationSubmission) => void;
  };
}>('project-workspace');

export const skillLibraryServices = context<{ apiBaseUrl: string; createInChat: (skill?: {id:string;title:string}) => Promise<void> }>('skill-library');
