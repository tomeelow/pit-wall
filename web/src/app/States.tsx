import type { ReactNode } from "react";
import { useT } from "./i18n";

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
  const t = useT();
  return (
    <div className="failure" role="alert">
      <h3>{t.failure}</h3>
      <p>{message}</p>
      <p>{t.failureHint}</p>
    </div>
  );
}

/** The assumptions every strategy result rests on, stated where the result is. */
export function Assumptions({ fromLap, events }: { fromLap: number; events: "sampled" | "realised" }) {
  const { assume } = useT();
  return (
    <ul className="assumptions">
      <Lead text={assume.rivals} />
      <Lead text={events === "sampled" ? assume.sampled(fromLap) : assume.realised} />
      <Lead text={assume.pace(fromLap)} />
    </ul>
  );
}

/** A list item that opens in bold. */
export function Lead({ text: [bold, rest] }: { text: readonly [string, string] }) {
  return (
    <li>
      <b>{bold}</b> {rest}
    </li>
  );
}
