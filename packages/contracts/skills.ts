export interface SkillResource { path: string; byteSize: number; sha256: string; mime: string }
export interface SkillSummary {
  id: string; name: string; title: string; description: string; version: number; currentVersion: number;
  enabled: boolean; deleted: boolean; contentHash: string; requiredTools: string[]; missingTools: string[];
  createdAt: string; updatedAt: string;
  source?: SkillSource | null; compatibilityWarnings?: string[]; explicitOnly?: boolean;
  builtin?: { name: string; revision: string; modifiedLocally: boolean };
}
export interface SkillDetail extends SkillSummary { instructions: string; resources: SkillResource[] }
export interface SkillVersion { version: number; contentHash: string; createdAt: string }
export interface SkillBinding { skillId: string; name: string; title: string; version: number; contentHash: string; active: boolean; resources?: SkillResource[] }
export interface SkillList { skills: SkillSummary[]; total: number; nextOffset: number | null }
export interface SkillResourceInput { path: string; text?: string; dataBase64?: string; existingPath?: string; sourceAssetId?: string; sourceDocumentId?: string }
export interface SkillInput {
  name: string; title: string; description: string; instructions: string;
  required_tools: string[]; resources: SkillResourceInput[]; enabled: boolean; expected_version?: number;
}

export interface SkillSource { owner: string; repo: string; ref: string; path: string; commit: string; url: string; modifiedLocally?: boolean }
export interface GitHubSkillInspection {
  source: SkillSource;
  candidates: { path: string; name?: string; title?: string; description?: string; warnings?: string[]; error?: string }[];
}
