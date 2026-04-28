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
};

export type TutorialEvent =
  | "chat-started"
  | "files-uploaded"
  | "definition-tab-clicked"
  | "definition-saved"
  | "config-tab-clicked"
  | "config-saved"
  | "run-completed";

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
      return session.tutorial_first_run_done
        ? session.tutorial_second_run_done
          ? null
          : { tutorial_second_run_done: true }
        : { tutorial_first_run_done: true };
  }
}
