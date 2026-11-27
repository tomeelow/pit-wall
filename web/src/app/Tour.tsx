import { useContext, useEffect, useId, useRef, useState } from "react";
import { Segmented } from "./Controls";
import { I18n, LANGS, STRINGS } from "./i18n";
import { placeCard, spotlight, TOUR, type Rect } from "./onboarding";
import type { Tab } from "./url";

/** Room kept around a lit element, so its outline is not cut. */
const PAD = 6;

interface Frame {
  hole: Rect | null;
  card: { top: number; left: number };
  glide?: boolean;
}

const same = (a: Frame | null, b: Frame) =>
  a !== null &&
  a.card.top === b.card.top &&
  a.card.left === b.card.left &&
  JSON.stringify(a.hole) === JSON.stringify(b.hole);

const holeIn = (r: Rect) =>
  `polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, 0 0, ${r.left}px ${r.top}px, ${r.left + r.width}px ${r.top}px, ${r.left + r.width}px ${r.top + r.height}px, ${r.left}px ${r.top + r.height}px, ${r.left}px ${r.top}px)`;

/**
 * A guided walk through the app. It dims the page and lights one control at a time, which stays
 * usable, so the viewer can try it before moving on.
 */
export function Tour({ onTab, onClose }: { onTab: (tab: Tab) => void; onClose: () => void }) {
  const { t, setLang } = useContext(I18n);
  const tx = t.tour;
  const [index, setIndex] = useState(0);
  const [frame, setFrame] = useState<Frame | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  // The card glides between steps but appears in place the first time.
  const placed = useRef(false);
  const titleId = useId();
  const step = TOUR[index]!;
  const copy = tx.steps[step.id];
  const last = index === TOUR.length - 1;

  const go = (next: number) => {
    const to = TOUR[next]!;
    if ("tab" in to) onTab(to.tab);
    setIndex(next);
  };

  // Targets load, move and resize as the page does, so they are measured every frame.
  useEffect(() => {
    const targets: readonly string[] = "targets" in step ? step.targets : [];
    let scrolled = false;
    let raf = 0;
    let shown: Frame | null = null;
    const tick = () => {
      const view = { width: innerWidth, height: innerHeight };
      const found = targets.flatMap((id) => [...document.querySelectorAll(`[data-tour="${id}"]`)]);
      if (!scrolled && found[0]) {
        scrolled = true;
        const el = found[0];
        const box = el.getBoundingClientRect();
        // The sticky bar covers the top of the page; what is in it never needs scrolling to.
        const bar = el.closest(".bar") ? 0 : (document.querySelector(".bar")?.getBoundingClientRect().bottom ?? 0);
        if (box.top < bar || box.bottom > view.height) {
          const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
          const tall = box.height > (view.height - bar) / 2;
          el.scrollIntoView({ block: tall ? "start" : "center", behavior: smooth ? "smooth" : "auto" });
        }
      }
      const hole = spotlight(
        found.map((el) => el.getBoundingClientRect()),
        PAD,
        view,
      );
      const card = cardRef.current;
      const size = card ? { width: card.offsetWidth, height: card.offsetHeight } : { width: 0, height: 0 };
      const next = { hole, card: placeCard(hole, size, view) };
      if (!same(shown, next)) {
        shown = next;
        setFrame({ ...next, glide: placed.current });
        placed.current = true;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [step]);

  useEffect(() => nextRef.current?.focus({ preventScroll: true }), [index]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      // Arrow keys belong to the lit control (a stop handle, a select) unless the card has focus.
      if (!(e.target instanceof Node && cardRef.current?.contains(e.target))) return;
      if (e.key === "ArrowRight" && !last) go(index + 1);
      if (e.key === "ArrowLeft" && index > 0) go(index - 1);
    };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  });

  const hole = frame?.hole ?? null;
  const centre = { top: innerHeight / 2, left: innerWidth / 2, width: 0, height: 0 };
  const ring = hole ?? centre;

  return (
    <div className="tour">
      <div className="tour-block" style={{ clipPath: hole ? holeIn(hole) : undefined }} />
      <div
        className={hole ? "tour-ring" : "tour-ring tour-ring-off"}
        style={{ top: ring.top, left: ring.left, width: ring.width, height: ring.height }}
        aria-hidden="true"
      />
      <div
        ref={cardRef}
        className={frame?.glide ? "tour-card tour-glide" : "tour-card"}
        role="dialog"
        aria-labelledby={titleId}
        style={{ top: frame?.card.top ?? 0, left: frame?.card.left ?? 0, visibility: frame ? "visible" : "hidden" }}
      >
        <div className="tour-progress" aria-hidden="true">
          <span style={{ width: `${((index + 1) / TOUR.length) * 100}%` }} />
        </div>
        <div key={step.id} className="tour-copy">
          <p className="sub num">{tx.step(index + 1, TOUR.length)}</p>
          <h2 id={titleId}>{copy.title}</h2>
          <p>{copy.body}</p>
          {copy.tryIt && (
            <p className="tour-try">
              <b>{tx.tryIt}</b> {copy.tryIt}
            </p>
          )}
          {step.id === "welcome" && (
            <Segmented
              label={tx.language}
              value={t.lang}
              onChange={setLang}
              options={LANGS.map((lang) => ({ value: lang, label: STRINGS[lang].langName }))}
            />
          )}
        </div>
        <div className="tour-actions">
          {!last && (
            <button type="button" className="link tour-skip" onClick={onClose}>
              {tx.skip}
            </button>
          )}
          {index > 0 && (
            <button type="button" className="quiet" onClick={() => go(index - 1)}>
              {tx.back}
            </button>
          )}
          <button ref={nextRef} type="button" className="tour-next" onClick={() => (last ? onClose() : go(index + 1))}>
            {index === 0 ? tx.start : last ? tx.finish : tx.next}
          </button>
        </div>
      </div>
    </div>
  );
}
