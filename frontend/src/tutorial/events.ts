import type { Session, TutorialStepId } from "@shared/api";

export type ParticipantTutorialPatch = {
  participant_tutorial_enabled?: boolean;
  tutorial_step_override?: TutorialStepId | null;
  tutorial_chat_started?: boolean;
  tutorial_uploaded_files?: boolean;
  tutorial_definition_tab_visited?: boolean;
  tutorial_definition_saved?: boolean;
  tutorial_config_tab_visited?: boolean;
  tutorial_config_saved?: boolean;
  tutorial_first_run_done?: boolean;
  tutorial_second_run_done?: boolean;
  tutorial_results_inspected?: boolean;
  tutorial_explain_used?: boolean;
  tutorial_candidate_marked?: boolean;
  tutorial_third_run_done?: boolean;
  tutorial_completed?: boolean;
};

export type TutorialEvent =
  | "chat-started"
  | "files-uploaded"
  | "definition-tab-clicked"
  | "definition-saved"
  | "config-tab-clicked"
  | "config-saved"
  | "run-completed"
  | "results-inspected"
  | "explain-used"
  | "candidate-marked";

export function patchForTutorialEvent(event: TutorialEvent, session: Session | null): ParticipantTutorialPatch | null {
  if (!session?.participant_tutorial_enabled) return null;
  switch (event) {
    case "chat-started":
      return session.tutorial_chat_started ? null : { tutorial_chat_started: true };
    case "files-uploaded":
      return session.tutorial_uploaded_files ? null : { tutorial_uploaded_files: true };
    case "definition-tab-clicked":
      return session.tutorial_definition_tab_visited ? null : { tutorial_definition_tab_visited: true };
    case "definition-saved":
      return session.tutorial_definition_saved ? null : { tutorial_definition_saved: true };
    case "config-tab-clicked":
      return session.tutorial_config_tab_visited ? null : { tutorial_config_tab_visited: true };
    case "config-saved":
      return session.tutorial_config_saved ? null : { tutorial_config_saved: true };
    case "run-completed":
      // Three-run progression: first → second → third. Each run completion
      // advances the lowest unfinished flag.
      if (!session.tutorial_first_run_done) return { tutorial_first_run_done: true };
      if (!session.tutorial_second_run_done) return { tutorial_second_run_done: true };
      if (!session.tutorial_third_run_done) return { tutorial_third_run_done: true };
      return null;
    case "results-inspected":
      return session.tutorial_results_inspected ? null : { tutorial_results_inspected: true };
    case "explain-used":
      return session.tutorial_explain_used ? null : { tutorial_explain_used: true };
    case "candidate-marked":
      return session.tutorial_candidate_marked ? null : { tutorial_candidate_marked: true };
  }
}
