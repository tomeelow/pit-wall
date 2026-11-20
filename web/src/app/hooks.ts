import { useCallback, useEffect, useRef, useState } from "react";
import { Cancelled, type Ticket } from "./lab";

export type Loaded<T> =
  | { status: "none" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; value: T };

/** One file of the bundle, reloaded when the path changes. `load` must be a stable function. */
export function useLoad<T>(path: string | null, load: (path: string) => Promise<T>): Loaded<T> {
  const [got, setGot] = useState<{ path: string; value?: T; error?: string }>();
  useEffect(() => {
    if (!path) return;
    let live = true;
    load(path).then(
      (value) => live && setGot({ path, value }),
      (error: unknown) => live && setGot({ path, error: String(error) }),
    );
    return () => {
      live = false;
    };
  }, [path, load]);
  if (!path) return { status: "none" };
  if (got?.path !== path) return { status: "loading" };
  if (got.error !== undefined) return { status: "error", message: got.error };
  return { status: "ready", value: got.value as T };
}

export type Run<T> =
  | { status: "idle" }
  | { status: "running"; races: number; partial: T | null }
  | { status: "done"; races: number; result: T }
  | { status: "error"; message: string };

export interface RunContext<T> {
  ticket: Ticket;
  addRaces: (n: number) => void;
  partial: (value: T) => void;
}

/** A simulation the user starts; starting again, or leaving the screen, cancels the last one. */
export function useRun<T>(): [Run<T>, (task: (ctx: RunContext<T>) => Promise<T>) => void] {
  const [state, setState] = useState<Run<T>>({ status: "idle" });
  const ticket = useRef<Ticket | null>(null);
  useEffect(
    () => () => {
      if (ticket.current) ticket.current.cancelled = true;
    },
    [],
  );
  const start = useCallback((task: (ctx: RunContext<T>) => Promise<T>) => {
    if (ticket.current) ticket.current.cancelled = true;
    const mine: Ticket = { cancelled: false };
    ticket.current = mine;
    let races = 0;
    let latest: T | null = null;
    const update = () => !mine.cancelled && setState({ status: "running", races, partial: latest });
    update();
    task({
      ticket: mine,
      addRaces: (n) => {
        races += n;
        update();
      },
      partial: (value) => {
        latest = value;
        update();
      },
    }).then(
      (result) => !mine.cancelled && setState({ status: "done", races, result }),
      (error: unknown) => {
        if (error instanceof Cancelled || mine.cancelled) return;
        setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
      },
    );
  }, []);
  return [state, start];
}
