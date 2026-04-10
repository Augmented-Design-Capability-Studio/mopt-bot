import { useEffect, useRef, type RefObject } from "react";

type UseLockedEditFocusArgs = {
  rootRef: RefObject<HTMLElement | null>;
  editable: boolean;
  focusSelector: string;
};

/**
 * Preserves scroll and focuses the first editable control when transitioning
 * from locked -> editable mode via a pointer interaction.
 */
export function useLockedEditFocus({ rootRef, editable, focusSelector }: UseLockedEditFocusArgs) {
  const shouldFocusOnEditRef = useRef(false);
  const scrollTopBeforeEditRef = useRef<number | null>(null);
  const preferredFocusSelectorRef = useRef<string | null>(null);
  const preferredCaretIndexRef = useRef<number | null>(null);

  const markLockedInteraction = (preferredFocusSelector?: string, preferredCaretIndex?: number) => {
    const root = rootRef.current;
    const scrollContainer = root?.closest(".config-panel-scroll") as HTMLElement | null;
    scrollTopBeforeEditRef.current = scrollContainer?.scrollTop ?? null;
    preferredFocusSelectorRef.current = preferredFocusSelector ?? null;
    preferredCaretIndexRef.current =
      typeof preferredCaretIndex === "number" && Number.isFinite(preferredCaretIndex) ? preferredCaretIndex : null;
    shouldFocusOnEditRef.current = true;
  };

  useEffect(() => {
    if (!editable || !shouldFocusOnEditRef.current) return;
    shouldFocusOnEditRef.current = false;
    const root = rootRef.current;
    if (!root) return;
    const scrollContainer = root.closest(".config-panel-scroll") as HTMLElement | null;
    const savedScrollTop = scrollTopBeforeEditRef.current;
    const preferredSelector = preferredFocusSelectorRef.current;
    const safeQuery = (selector: string): HTMLElement | null => {
      try {
        return root.querySelector<HTMLElement>(selector);
      } catch {
        return null;
      }
    };
    // If a specific control was clicked, focus only that control after edit mode opens.
    // Do not fall back to the first field, which can feel like "focus jumping".
    const firstEditable = preferredSelector ? safeQuery(preferredSelector) : safeQuery(focusSelector);
    if (firstEditable) {
      firstEditable.focus({ preventScroll: true });
      const caretIndex = preferredCaretIndexRef.current;
      if (
        caretIndex != null &&
        (firstEditable instanceof HTMLInputElement || firstEditable instanceof HTMLTextAreaElement)
      ) {
        // setSelectionRange throws for unsupported input types (e.g., number).
        // Keep focus behavior robust and never crash the page on click.
        const valueLen = firstEditable.value.length;
        const safeIndex = Math.max(0, Math.min(valueLen, caretIndex));
        try {
          if (firstEditable instanceof HTMLTextAreaElement) {
            firstEditable.setSelectionRange(safeIndex, safeIndex);
          } else if (firstEditable.type !== "number") {
            firstEditable.setSelectionRange(safeIndex, safeIndex);
          }
        } catch {
          // Ignore caret placement failures; focus alone is sufficient.
        }
      }
    }
    if (scrollContainer && savedScrollTop != null) {
      requestAnimationFrame(() => {
        scrollContainer.scrollTop = savedScrollTop;
      });
    }
    preferredFocusSelectorRef.current = null;
    preferredCaretIndexRef.current = null;
    scrollTopBeforeEditRef.current = null;
  }, [editable, focusSelector, rootRef]);

  return { markLockedInteraction };
}
