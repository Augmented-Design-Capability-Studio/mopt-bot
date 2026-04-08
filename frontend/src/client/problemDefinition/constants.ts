/** New gathered/assumption rows use this until the user saves real text; omitted from server PATCH. */
export const DEFINITION_NEW_ROW_PLACEHOLDER = "Click to edit";

/** Posted as a user chat message; must match backend `is_definition_cleanup_request` intent patterns. */
export const DEFINITION_CLEANUP_CHAT_MESSAGE =
  "Please clean up and consolidate my problem definition: deduplicate redundant gathered facts and assumptions, and keep unresolved items in open questions.";
