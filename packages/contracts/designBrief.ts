/** Agent-derived wording. Original user messages and sourced decisions win. */
export type DesignEvidence = {
  source: 'user' | 'reference' | 'research' | 'lesson' | 'assumption';
  reference?: string;
  use: string;
};
export type VisualDirection = {
  audience: string; theme: string; coreConcept: string;
  visualHierarchy: string[]; formLanguage: string[]; materialProcess: string[];
  colorRelationships: string[]; compositionLighting: string[]; avoid: string[];
  evidence: DesignEvidence[];
};
export type DesignBrief = {
  summary: string;
  assumptions: string[];
  openQuestions: string[];
  visualDirection?: VisualDirection;
  sourceTaskId: string;
  status: 'derived';
};
