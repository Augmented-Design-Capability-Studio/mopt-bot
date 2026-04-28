export type ParticipantOpsState = {
  savingConfig: boolean;
  savingDefinition: boolean;
  cleaningOpenQuestions: boolean;
  syncingConfig: boolean;
  restoringSnapshot: boolean;
  sendingChat: boolean;
};

export const DEFAULT_PARTICIPANT_OPS_STATE: ParticipantOpsState = {
  savingConfig: false,
  savingDefinition: false,
  cleaningOpenQuestions: false,
  syncingConfig: false,
  restoringSnapshot: false,
  sendingChat: false,
};
