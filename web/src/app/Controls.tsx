import { useId } from "react";
import { useT } from "./i18n";

/** A row of radio buttons styled as one control. */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const name = useId();
  return (
    <fieldset className="field">
      <legend>{label}</legend>
      <div className="segmented">
        {options.map((o) => (
          <label key={o.value}>
            <input
              type="radio"
              name={name}
              value={o.value}
              checked={o.value === value}
              onChange={() => onChange(o.value)}
            />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** The lap a decision is taken after, from the laps with a race state for this car. */
export function LapField({
  label,
  laps,
  value,
  total,
  onChange,
}: {
  label: string;
  laps: readonly number[];
  value: number;
  total: number;
  onChange: (lap: number) => void;
}) {
  const id = useId();
  const t = useT();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className="input" value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {laps.map((lap) => (
          <option key={lap} value={lap}>
            {t.lapOf(lap, total)}
          </option>
        ))}
      </select>
    </div>
  );
}

export function Pick<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        className="input"
        value={value}
        onChange={(e) => {
          const picked = options.find((o) => String(o.value) === e.target.value);
          if (picked) onChange(picked.value);
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export const percent = (x: number) => `${Math.round(x * 100)}%`;
export const signed = (x: number, digits = 2) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(digits)}`;
