import type { ReactNode } from "react";

/** Grey rows in the shape of what is coming. */
export function Skeleton({ rows = 6, label }: { rows?: number; label: string }) {
  return (
    <div className="skeleton" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, k) => (
        <span key={k} />
      ))}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}

export function Failure({ message }: { message: string }) {
  return (
    <div className="failure" role="alert">
      <h3>That did not work</h3>
      <p>{message}</p>
      <p>Reload the page to try again; if it keeps failing, the race bundle may be out of date.</p>
    </div>
  );
}

/** The assumptions every strategy result rests on, stated where the result is. */
export function Assumptions({ fromLap, events }: { fromLap: number; events: "sampled" | "realised" }) {
  return (
    <ul className="assumptions">
      <li>
        <b>Rivals keep their real strategies.</b> They do not react to this plan.
      </li>
      <li>
        {events === "sampled" ? (
          <>
            <b>Safety cars, red flags and retirements are drawn at random</b> after lap {fromLap},
            never replayed: only what was knowable at lap {fromLap}.
          </>
        ) : (
          <>
            <b>Safety cars and red flags happen when they really did.</b> That is hindsight: it
            says whether the plan worked out, not whether it was a good call.
          </>
        )}
      </li>
      <li>
        <b>Pace is fitted on the whole race,</b> a known softening of the lap-{fromLap} view.
      </li>
    </ul>
  );
}
