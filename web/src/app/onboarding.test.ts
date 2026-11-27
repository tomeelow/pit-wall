import { describe, expect, it } from "vitest";
import { LANGS, STRINGS } from "./i18n";
import { placeCard, spotlight, TOUR } from "./onboarding";
import { TABS } from "./url";

const view = { width: 1200, height: 800 };
const card = { width: 360, height: 200 };

describe("placeCard", () => {
  it("puts the card below the target, centred on it", () => {
    expect(placeCard({ top: 10, left: 400, width: 200, height: 40 }, card, view)).toEqual({ top: 64, left: 320 });
  });

  it("goes above, then beside, when there is no room below", () => {
    expect(placeCard({ top: 600, left: 400, width: 200, height: 100 }, card, view).top).toBe(386);
    const tall = { top: 60, left: 700, width: 480, height: 700 };
    expect(placeCard(tall, card, view)).toEqual({ top: 310, left: 326 });
  });

  it("sits over the foot of a target that fills the window, and stays on screen", () => {
    expect(placeCard({ top: 0, left: 0, width: 1200, height: 800 }, card, view)).toEqual({ top: 588, left: 420 });
    expect(placeCard({ top: 10, left: 1150, width: 40, height: 30 }, card, view).left).toBe(828);
  });

  it("centres the card when nothing is lit", () => {
    expect(placeCard(null, card, view)).toEqual({ top: 300, left: 420 });
  });
});

describe("spotlight", () => {
  it("wraps every lit element, padded and cut to the window", () => {
    const rects = [
      { top: 20, left: 100, width: 50, height: 20 },
      { top: 30, left: 180, width: 50, height: 20 },
    ];
    expect(spotlight(rects, 6, view)).toEqual({ top: 14, left: 94, width: 142, height: 42 });
    expect(spotlight([{ top: -50, left: 0, width: 100, height: 900 }], 6, view)).toEqual({
      top: 0,
      left: 0,
      width: 106,
      height: 800,
    });
  });

  it("lights nothing for a missing or scrolled-away target", () => {
    expect(spotlight([], 6, view)).toBeNull();
    expect(spotlight([{ top: 900, left: 0, width: 100, height: 40 }], 6, view)).toBeNull();
  });
});

describe("the tour", () => {
  const sources = Object.values(import.meta.glob<string>("./*.tsx", { query: "?raw", import: "default", eager: true }));
  const marked = new Set(sources.flatMap((src) => [...src.matchAll(/data-tour="([^"]+)"/g)].map((m) => m[1]!)));
  if (sources.some((src) => src.includes("data-tour={`tab-${tab}`}"))) TABS.forEach((tab) => marked.add(`tab-${tab}`));

  it("lights only elements the app marks", () => {
    const targets = TOUR.flatMap((step) => ("targets" in step ? step.targets : []));
    expect(targets.filter((target) => !marked.has(target))).toEqual([]);
  });

  it("has every card written in every language", () => {
    for (const lang of LANGS) {
      for (const step of TOUR) {
        const copy = STRINGS[lang].tour.steps[step.id];
        expect(copy.title.length * copy.body.length, `${lang} ${step.id}`).toBeGreaterThan(0);
      }
    }
  });
});
