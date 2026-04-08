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
    const firstEditable = preferredSelector
      ? root.querySelector<HTMLElement>(preferredSelector) ?? root.querySelector<HTMLElement>(focusSelector)
      : root.querySelector<HTMLElement>(focusSelector);
    if (firstEditable) {
      firstEditable.focus({ preventScroll: true });
      const caretIndex = preferredCaretIndexRef.current;
      if (
        caretIndex != null &&
        (firstEditable instanceof HTMLInputElement || firstEditable instanceof HTMLTextAreaElement)
      ) {
        const valueLen = firstEditable.value.length;
        const safeIndex = Math.max(0, Math.min(valueLen, caretIndex));
        firstEditable.setSelectionRange(safeIndex, safeIndex);
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
