export type ParticipantOpsState = {
  savingConfig: boolean;
  savingDefinition: boolean;
  cleaningOpenQuestions: boolean;
  syncingConfig: boolean;
  restoringSnapshot: boolean;
  sendingChat: boolean;
  // OQ ids whose answers are being rephrased + bucket-routed by the backend
  // classifier. The card shows a spinning shield and locks input while present.
  processingOqIds: ReadonlySet<string>;
};

export const DEFAULT_PARTICIPANT_OPS_STATE: ParticipantOpsState = {
  savingConfig: false,
  savingDefinition: false,
  cleaningOpenQuestions: false,
  syncingConfig: false,
  restoringSnapshot: false,
  sendingChat: false,
  processingOqIds: new Set<string>(),
};
