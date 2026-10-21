/** Findings are independent: a usable visual can still need fabrication specs. */
export type DeliveryFindingKind = 'problem' | 'unverified' | 'production_confirmation' | 'generation_unconfirmed';
export type DeliveryRepair = { change: string; preserve: string[] };
export type DeliveryFinding = {
  kind: DeliveryFindingKind;
  code: string;
  message: string;
  nextAction: string;
  nodeId?: string;
  planItemId?: string;
  /** Exists only for an evidence-backed reviewer error; starts no task by itself. */
  repair?: DeliveryRepair;
  sourceTaskId?: string;
  artifactFingerprint?: string;
};
