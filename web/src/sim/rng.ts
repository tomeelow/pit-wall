// xoshiro128**: a small, fast, seedable PRNG. Every random number in the engine comes from here.

const TWO_POW_MINUS_32 = 2 ** -32;

function splitmix32(state: number): [number, number] {
  const next = (state + 0x9e3779b9) | 0;
  let z = next;
  z = Math.imul(z ^ (z >>> 16), 0x85ebca6b);
  z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35);
  return [next, (z ^ (z >>> 16)) >>> 0];
}

export class Rng {
  private s0: number;
  private s1: number;
  private s2: number;
  private s3: number;

  /** One independent stream per (seed, stream): simulation i of a query uses stream i. */
  constructor(seed: number, stream = 0) {
    let state = (seed ^ Math.imul(stream, 0x632be5ab)) | 0;
    const words: number[] = [];
    for (let k = 0; k < 4; k++) {
      const [next, value] = splitmix32(state);
      state = next;
      words.push(value);
    }
    [this.s0, this.s1, this.s2, this.s3] = words as [number, number, number, number];
  }

  nextUint32(): number {
    const result = Math.imul(rotl(Math.imul(this.s1, 5), 7), 9) >>> 0;
    const t = this.s1 << 9;
    this.s2 ^= this.s0;
    this.s3 ^= this.s1;
    this.s1 ^= this.s2;
    this.s0 ^= this.s3;
    this.s2 ^= t;
    this.s3 = rotl(this.s3, 11);
    return result;
  }

  /** Uniform on [0, 1). */
  uniform(): number {
    return this.nextUint32() * TWO_POW_MINUS_32;
  }

  normal(): number {
    const u = 1 - this.uniform();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * this.uniform());
  }

  /** Gamma(shape, 1), Marsaglia and Tsang. */
  gamma(shape: number): number {
    if (shape < 1) return this.gamma(shape + 1) * (1 - this.uniform()) ** (1 / shape);
    const d = shape - 1 / 3;
    const c = 1 / Math.sqrt(9 * d);
    for (;;) {
      const x = this.normal();
      const v = (1 + c * x) ** 3;
      if (v <= 0) continue;
      const u = 1 - this.uniform();
      if (Math.log(u) < 0.5 * x * x + d - d * v + d * Math.log(v)) return d * v;
    }
  }

  /** Standard Student-t with `nu` degrees of freedom. */
  studentT(nu: number): number {
    return this.normal() / Math.sqrt((2 * this.gamma(nu / 2)) / nu);
  }
}

function rotl(x: number, k: number): number {
  return (x << k) | (x >>> (32 - k));
}
