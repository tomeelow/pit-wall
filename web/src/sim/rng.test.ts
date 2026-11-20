import { describe, expect, it } from "vitest";
import { Rng } from "./rng.ts";

function moments(sample: (rng: Rng) => number, n = 40_000) {
  const rng = new Rng(7);
  let sum = 0;
  let squares = 0;
  for (let k = 0; k < n; k++) {
    const x = sample(rng);
    sum += x;
    squares += x * x;
  }
  const mean = sum / n;
  return { mean, variance: squares / n - mean * mean };
}

describe("Rng", () => {
  it("repeats a stream for the same seed and stream, and differs otherwise", () => {
    const take = (rng: Rng) => Array.from({ length: 5 }, () => rng.nextUint32());
    expect(take(new Rng(1, 3))).toEqual(take(new Rng(1, 3)));
    expect(take(new Rng(1, 3))).not.toEqual(take(new Rng(1, 4)));
    expect(take(new Rng(1, 3))).not.toEqual(take(new Rng(2, 3)));
  });

  it("draws uniforms on [0, 1)", () => {
    const rng = new Rng(3);
    const values = Array.from({ length: 10_000 }, () => rng.uniform());
    expect(Math.min(...values)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...values)).toBeLessThan(1);
    expect(moments((r) => r.uniform()).mean).toBeCloseTo(0.5, 2);
  });

  it("draws normal, gamma and Student-t variates with the right moments", () => {
    const normal = moments((r) => r.normal());
    expect(normal.mean).toBeCloseTo(0, 1);
    expect(normal.variance).toBeCloseTo(1, 1);
    expect(moments((r) => r.gamma(3)).mean).toBeCloseTo(3, 1);
    expect(moments((r) => r.gamma(0.5)).mean).toBeCloseTo(0.5, 1);
    // Var(t_nu) = nu / (nu - 2)
    expect(moments((r) => r.studentT(6)).variance).toBeCloseTo(1.5, 1);
  });
});
