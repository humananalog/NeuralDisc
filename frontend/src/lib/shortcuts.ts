/** Lightroom-style media shortcuts — single source of truth for the app. */

export type ShortcutDef = {
  keys: string[];
  label: string;
  group: string;
};

/** Shown in the `?` help overlay and used as documentation. */
export const MEDIA_SHORTCUTS: ShortcutDef[] = [
  { keys: ["←", "→", "j", "k"], label: "Previous / next", group: "Navigate" },
  { keys: ["Enter"], label: "Open detail panel", group: "Navigate" },
  { keys: ["Backspace"], label: "Expand / close lightbox", group: "Navigate" },
  { keys: ["Esc"], label: "Close overlay · clear selection", group: "Navigate" },
  { keys: ["⌘A"], label: "Select all in view", group: "Navigate" },

  { keys: ["0"], label: "Clear rating", group: "Rate & flag" },
  { keys: ["1–5"], label: "Set star rating", group: "Rate & flag" },
  { keys: ["f", "p"], label: "Toggle / set pick flag", group: "Rate & flag" },
  { keys: ["u"], label: "Unflag", group: "Rate & flag" },

  { keys: ["["], label: "Rotate 90° left", group: "Rotate" },
  { keys: ["]"], label: "Rotate 90° right", group: "Rotate" },
  { keys: ["⇧["], label: "Auto-rotate (EXIF + content)", group: "Rotate" },
  { keys: ["⇧]"], label: "Rotate 180°", group: "Rotate" },

  { keys: ["Delete"], label: "Trash / delete selection", group: "Edit" },
  { keys: ["+", "−", "0"], label: "Zoom in / out / reset (lightbox)", group: "Lightbox" },
  { keys: ["?"], label: "Show keyboard shortcuts", group: "Help" },
];

export function isTypingTarget(target: EventTarget | null): boolean {
  const t = target as HTMLElement | null;
  if (!t) return false;
  if (t.isContentEditable) return true;
  const tag = t.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return Boolean(t.closest?.("[data-no-shortcuts]"));
}

/** True when a modal/dialog besides our media chrome should own keys. */
export function isBlockingOverlay(): boolean {
  if (typeof document === "undefined") return false;
  return Boolean(
    document.querySelector(
      '[role="dialog"][data-blocking-shortcuts="true"], [data-blocking-shortcuts="true"]',
    ),
  );
}
