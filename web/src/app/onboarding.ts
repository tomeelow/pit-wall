import type { Tab } from "./url";

/** A tour step lights up the elements marked `data-tour="<target>"`, on its tab if it names one. */
interface Step {
  id: string;
  tab?: Tab;
  targets?: readonly string[];
}

export const TOUR = [
  { id: "welcome" },
  { id: "race", targets: ["race"] },
  { id: "driver", targets: ["driver"] },
  { id: "tabs", targets: ["tabs"] },
  { id: "raceView", tab: "race", targets: ["race-view"] },
  { id: "decide", tab: "whatif", targets: ["decide"] },
  { id: "drag", tab: "whatif", targets: ["lanes"] },
  { id: "stops", tab: "whatif", targets: ["stops"] },
  { id: "run", tab: "whatif", targets: ["run"] },
  { id: "results", tab: "whatif", targets: ["results"] },
  { id: "optimise", tab: "optimise", targets: ["optimise"] },
  { id: "undercut", tab: "undercut", targets: ["undercut"] },
  { id: "debrief", tab: "debrief", targets: ["debrief"] },
  { id: "replay", tab: "replay", targets: ["tab-replay", "tab-telemetry"] },
  { id: "model", tab: "model", targets: ["tab-model"] },
  { id: "done", tab: "whatif", targets: ["help"] },
] as const satisfies readonly Step[];

export type StepId = (typeof TOUR)[number]["id"];

export interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/** Room left between the card and the target, and between the card and the window edge. */
const GAP = 14;
const MARGIN = 12;

const clamp = (x: number, lo: number, hi: number) => Math.min(Math.max(x, lo), Math.max(lo, hi));

/**
 * Where the card goes: below the target, else above, right, left; over its foot when none has room,
 * as for a panel that fills the window. Centred when there is no target.
 */
export function placeCard(target: Rect | null, card: { width: number; height: number }, view: { width: number; height: number }) {
  const centre = (size: number, room: number) => clamp((room - size) / 2, MARGIN, room - MARGIN - size);
  if (!target) return { top: centre(card.height, view.height), left: centre(card.width, view.width) };
  const bottom = target.top + target.height;
  const right = target.left + target.width;
  const alongX = clamp(target.left + target.width / 2 - card.width / 2, MARGIN, view.width - MARGIN - card.width);
  const alongY = clamp(target.top + target.height / 2 - card.height / 2, MARGIN, view.height - MARGIN - card.height);
  if (bottom + GAP + card.height <= view.height - MARGIN) return { top: bottom + GAP, left: alongX };
  if (target.top - GAP - card.height >= MARGIN) return { top: target.top - GAP - card.height, left: alongX };
  if (right + GAP + card.width <= view.width - MARGIN) return { top: alongY, left: right + GAP };
  if (target.left - GAP - card.width >= MARGIN) return { top: alongY, left: target.left - GAP - card.width };
  return { top: view.height - MARGIN - card.height, left: alongX };
}

/** The smallest rectangle around all of `rects`, grown by `pad` and cut to the window. */
export function spotlight(rects: readonly Rect[], pad: number, view: { width: number; height: number }): Rect | null {
  if (rects.length === 0) return null;
  const top = Math.max(0, Math.min(...rects.map((r) => r.top)) - pad);
  const left = Math.max(0, Math.min(...rects.map((r) => r.left)) - pad);
  const bottom = Math.min(view.height, Math.max(...rects.map((r) => r.top + r.height)) + pad);
  const right = Math.min(view.width, Math.max(...rects.map((r) => r.left + r.width)) + pad);
  if (bottom <= top || right <= left) return null;
  return { top, left, width: right - left, height: bottom - top };
}

const STORAGE_KEY = "tour";

/** Blocked storage counts as seen: better no tour than one on every visit. */
export function tourSeen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "seen";
  } catch {
    return true;
  }
}

export function markTourSeen() {
  try {
    localStorage.setItem(STORAGE_KEY, "seen");
  } catch {
    // Storage can be blocked; the tour then stays closed until reload.
  }
}
